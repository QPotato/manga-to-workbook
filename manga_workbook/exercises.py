"""Build offline study drills from workbook data (no LLM).

Everything here is a deterministic re-rendering of data the pipeline already
computed (OCR text, fugashi tokens/lemmas, furigana, opus-mt glosses, page order).
Shuffles use a fixed seed (the chapter name) so output is reproducible.

Output: {"sections": [...], "answers": [...]} where each section/answer is
{"title", "instructions"?, "items": [html, ...]}. `items` are ready-to-place HTML
fragments; render.py only lays them out.
"""
import random

BLANK = '<span class="blank"></span>'
COMMON_PARTICLES = ["は", "が", "を", "に", "で", "と", "も", "へ", "から", "より", "や"]

_LIMITS = {"cloze": 12, "vocab": 24, "conj": 15, "fill": 10, "particle": 10, "seq": 3}


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _has_kanji(furigana_html: str) -> bool:
    return "<ruby>" in furigana_html


def _all_lines(wb):
    lines = []
    for pi, page in enumerate(wb["pages"]):
        for d in page["dialog"]:
            lines.append((pi, d))
    return lines


def _num(items):
    """Wrap each item as a numbered prompt with a writing line."""
    return [f'<span class="qn">{i}.</span> {it}' for i, it in enumerate(items, 1)]


def build_exercises(wb):
    rng = random.Random(wb.get("chapter", "chapter"))
    lines = _all_lines(wb)
    sections, answers = [], []

    def add(title, instructions, prompts, ans):
        if not prompts:
            return
        sections.append({"title": title, "instructions": instructions, "items": _num(prompts)})
        answers.append({"title": title, "items": _num(ans)})

    # 1. Furigana cloze: read the kanji, write the reading. Answer = the furigana.
    cloze = [d for _, d in lines if _has_kanji(d["furigana"]) and len(d["plain"]) <= 24]
    rng.shuffle(cloze)
    cloze = cloze[:_LIMITS["cloze"]]
    add("Furigana cloze 読み", "Write the reading (hiragana) for each line.",
        [f'<span class="big">{_esc(d["plain"])}</span>' for d in cloze],
        [f'<span class="big">{d["furigana"]}</span>' for d in cloze])

    # 2. Vocabulary recall (JA -> EN).
    vocab = (wb["summary_vocab"]["verbs"] + wb["summary_vocab"]["nouns"]
             + wb["summary_vocab"]["adjectives"])
    vocab = [v for v in vocab if v.get("en")]
    rng.shuffle(vocab)
    vocab = vocab[:_LIMITS["vocab"]]
    add("Vocabulary recall 単語", "Write the English meaning of each word.",
        [f'<span class="big">{v["furigana"]}</span> {BLANK}' for v in vocab],
        [f'<span class="big">{v["furigana"]}</span> — {_esc(v["en"])}' for v in vocab])

    # 3. Conjugation -> dictionary form (surface != lemma for verbs/adjectives).
    conj, seen = [], set()
    pool = [t for _, d in lines for t in d["tokens"]
            if t["p"] in ("動詞", "形容詞") and t["s"] != t["l"] and len(t["s"]) >= 2]
    rng.shuffle(pool)
    for t in pool:
        if t["s"] in seen:
            continue
        seen.add(t["s"])
        conj.append(t)
        if len(conj) >= _LIMITS["conj"]:
            break
    add("Dictionary form 辞書形", "Write the dictionary (plain) form of each word.",
        [f'<span class="big">{_esc(t["s"])}</span> &rarr; {BLANK}' for t in conj],
        [f'<span class="big">{_esc(t["s"])}</span> &rarr; {_esc(t["l"])}' for t in conj])

    # 4. Fill-in-the-blank: blank a noun/verb in a line, give a small word bank.
    fill = []
    cand = [(pi, d, t) for pi, d in lines for t in d["tokens"]
            if t["p"] in ("名詞", "動詞") and len(t["s"]) >= 2 and t["s"] in d["plain"]]
    rng.shuffle(cand)
    used_lines = set()
    bank_pool = list({t["s"] for _, _, t in cand})
    for pi, d, t in cand:
        if id(d) in used_lines:
            continue
        used_lines.add(id(d))
        blanked = d["plain"].replace(t["s"], "____", 1)
        distractors = rng.sample([w for w in bank_pool if w != t["s"]],
                                  k=min(3, max(0, len(bank_pool) - 1)))
        bank = [t["s"]] + distractors
        rng.shuffle(bank)
        prompt = (f'<span class="big">{_esc(blanked)}</span>'
                  f'<span class="bank">[ {" / ".join(_esc(b) for b in bank)} ]</span>')
        fill.append((prompt, t["s"]))
        if len(fill) >= _LIMITS["fill"]:
            break
    add("Fill in the blank 穴埋め", "Choose the word that fills each blank.",
        [p for p, _ in fill],
        [f'<span class="big">{_esc(a)}</span>' for _, a in fill])

    # 5. Particle blanks: blank one 助詞 token, learner supplies it.
    part = []
    pcand = [(d, t) for _, d in lines for t in d["tokens"]
             if t["p"] == "助詞" and t["s"] in COMMON_PARTICLES and t["s"] in d["plain"]]
    rng.shuffle(pcand)
    pused = set()
    for d, t in pcand:
        if id(d) in pused or len(d["plain"]) < 4:
            continue
        pused.add(id(d))
        blanked = d["plain"].replace(t["s"], "（　）", 1)
        part.append((blanked, t["s"]))
        if len(part) >= _LIMITS["particle"]:
            break
    add("Particles 助詞",
        f'Fill each （　） with a particle: {" ".join(COMMON_PARTICLES)}',
        [f'<span class="big">{_esc(b)}</span>' for b, _ in part],
        [f'<span class="big">{_esc(a)}</span>' for _, a in part])

    # 6. Sequencing: shuffle a page's dialogue, learner restores the reading order.
    seq_pages = [(pi, wb["pages"][pi]) for pi in sorted({pi for pi, _ in lines})
                 if 3 <= len(wb["pages"][pi]["dialog"]) <= 7]
    rng.shuffle(seq_pages)
    for pi, pg in seq_pages[:_LIMITS["seq"]]:
        shuffled = list(range(len(pg["dialog"])))
        rng.shuffle(shuffled)
        prompts = [f'{BLANK} {pg["dialog"][j]["furigana"]}' for j in shuffled]
        # The original order IS the correct reading order (boxes already RTL-sorted).
        ans = [f'<span class="qn">{i}.</span> {d["furigana"]}'
               for i, d in enumerate(pg["dialog"], 1)]
        sections.append({
            "title": f"Sequencing 並べ替え — page {pi + 1}",
            "instructions": "Number these lines in the correct reading order (right-to-left, top-to-bottom).",
            "items": prompts,
        })
        answers.append({"title": f"Sequencing 並べ替え — page {pi + 1}", "items": ans})

    return {"sections": sections, "answers": answers}
