"""Build offline study drills from workbook data (no LLM).

Everything here is a deterministic re-rendering of data the pipeline already
computed (OCR text, spaCy tokens/lemmas/POS, en->es glosses, page order).
Shuffles use a fixed seed (the chapter name) so output is reproducible.

Instructions are written in Spanish (the learner's native language); the material
the learner studies is the English text. Output: {"sections": [...], "answers":
[...]} where each section/answer is {"title", "instructions"?, "items": [html, ...]}.
`items` are ready-to-place HTML fragments; render.py only lays them out.
"""
import random
import re

from .language import is_real_word

BLANK = '<span class="blank"></span>'
# Common English prepositions for the preposition drill (the analog of the JP
# particle exercise — the small closed class learners must place correctly).
COMMON_PREPS = ["in", "on", "at", "to", "of", "for", "with", "from",
                "by", "about", "into", "over", "under", "between"]

_LIMITS = {"vocab": 24, "base": 15, "fill": 10, "prep": 10, "seq": 3}


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _blank_word(text: str, word: str, placeholder: str) -> str:
    """Replace the first whole-word occurrence of `word` in `text`."""
    return re.sub(rf"\b{re.escape(word)}\b", placeholder, text, count=1)


def _real_word_token(t) -> bool:
    """A content word safe to blank as a fill-in answer: a noun, verb or adjective
    of at least 3 letters, real (in the frequency corpus, so OCR garble like
    "becalse" is skipped)."""
    return (t["p"] in ("NOUN", "VERB", "ADJ") and len(t["s"]) >= 3
            and t["s"].isalpha() and is_real_word(t["l"]))


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

    # 1. Vocabulary recall (EN -> ES).
    vocab = (wb["summary_vocab"]["verbs"] + wb["summary_vocab"]["nouns"]
             + wb["summary_vocab"]["adjectives"])
    vocab = [v for v in vocab if v.get("es")]
    rng.shuffle(vocab)
    vocab = vocab[:_LIMITS["vocab"]]
    add("Vocabulario", "Escribe el significado en español de cada palabra.",
        [f'<span class="big">{_esc(v["word"])}</span> {BLANK}' for v in vocab],
        [f'<span class="big">{_esc(v["word"])}</span> &mdash; {_esc(v["es"])}' for v in vocab])

    # 2. Base form: inflected surface -> lemma (ran -> run, children -> child).
    base, seen = [], set()
    pool = [t for _, d in lines for t in d["tokens"]
            if t["p"] in ("VERB", "NOUN", "ADJ") and t["s"].lower() != t["l"]
            and len(t["s"]) >= 3 and t["s"].isalpha() and is_real_word(t["l"])]
    rng.shuffle(pool)
    for t in pool:
        key = t["s"].lower()
        if key in seen:
            continue
        seen.add(key)
        base.append(t)
        if len(base) >= _LIMITS["base"]:
            break
    add("Forma base", "Escribe la forma base (de diccionario) de cada palabra.",
        [f'<span class="big">{_esc(t["s"])}</span> &rarr; {BLANK}' for t in base],
        [f'<span class="big">{_esc(t["s"])}</span> &rarr; {_esc(t["l"])}' for t in base])

    # 3. Fill-in-the-blank: blank a content word in a line, give a small word bank.
    fill = []
    cand = [(pi, d, t) for pi, d in lines for t in d["tokens"]
            if _real_word_token(t) and re.search(rf'\b{re.escape(t["s"])}\b', d["text"])]
    rng.shuffle(cand)
    used_lines = set()
    bank_pool = list({t["s"] for _, _, t in cand})
    for pi, d, t in cand:
        if id(d) in used_lines:
            continue
        used_lines.add(id(d))
        blanked = _blank_word(d["text"], t["s"], "____")
        distractors = rng.sample([w for w in bank_pool if w != t["s"]],
                                  k=min(3, max(0, len(bank_pool) - 1)))
        bank = [t["s"]] + distractors
        rng.shuffle(bank)
        prompt = (f'<span class="big">{_esc(blanked)}</span>'
                  f'<span class="bank">[ {" / ".join(_esc(b) for b in bank)} ]</span>')
        fill.append((prompt, t["s"]))
        if len(fill) >= _LIMITS["fill"]:
            break
    add("Completa el espacio", "Elige la palabra que completa cada espacio.",
        [p for p, _ in fill],
        [f'<span class="big">{_esc(a)}</span>' for _, a in fill])

    # 4. Preposition blanks: blank one preposition, learner supplies it.
    prep = []
    pcand = [(d, t) for _, d in lines for t in d["tokens"]
             if t["p"] == "ADP" and t["s"].lower() in COMMON_PREPS
             and re.search(rf'\b{re.escape(t["s"])}\b', d["text"])]
    rng.shuffle(pcand)
    pused = set()
    for d, t in pcand:
        if id(d) in pused or len(d["text"]) < 8:
            continue
        pused.add(id(d))
        blanked = _blank_word(d["text"], t["s"], "( ____ )")
        prep.append((blanked, t["s"].lower()))
        if len(prep) >= _LIMITS["prep"]:
            break
    add("Preposiciones",
        f'Completa cada espacio con una preposición: {" · ".join(COMMON_PREPS)}',
        [f'<span class="big">{_esc(b)}</span>' for b, _ in prep],
        [f'<span class="big">{_esc(a)}</span>' for _, a in prep])

    # 5. Sequencing: shuffle a page's dialogue, learner restores the reading order.
    seq_pages = [(pi, wb["pages"][pi]) for pi in sorted({pi for pi, _ in lines})
                 if 3 <= len(wb["pages"][pi]["dialog"]) <= 7]
    rng.shuffle(seq_pages)
    for pi, pg in seq_pages[:_LIMITS["seq"]]:
        shuffled = list(range(len(pg["dialog"])))
        rng.shuffle(shuffled)
        prompts = [f'{BLANK} {_esc(pg["dialog"][j]["text"])}' for j in shuffled]
        # The original order IS the correct reading order (boxes already LTR-sorted).
        ans = [f'<span class="qn">{i}.</span> {_esc(d["text"])}'
               for i, d in enumerate(pg["dialog"], 1)]
        sections.append({
            "title": f"Ordena las viñetas — página {pi + 1}",
            "instructions": "Numera estas líneas en el orden de lectura correcto (izquierda a derecha, arriba a abajo).",
            "items": prompts,
        })
        answers.append({"title": f"Ordena las viñetas — página {pi + 1}", "items": ans})

    return {"sections": sections, "answers": answers}
