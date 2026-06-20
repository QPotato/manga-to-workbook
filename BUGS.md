# Workbook quality bugs

Findings from inspecting `workbooks/workbook-{3,4,5}.pdf` (Chainsaw Man, Code
Geass ×5 vol, SnK + Dungeon Meshi). Ranked by gravity × ease. Checkboxes track
the fix order.

## Works correctly (do not touch)
- **Conjugation drills** (辞書形): solid. 殺し→殺す, 倒れ→倒れる, 死ね→死ぬ, できる→出来る.
- **Furigana on normal bubble text**: readings right; okurigana split good (深ふかい).
- **Cleaning**: speech bubbles emptied correctly.

## Bugs (fix order)

| # | order | bug | evidence | gravity | effort |
|---|-------|-----|----------|---------|--------|
| 3 | 1 | **`_clean` tag leak** — unescapes AFTER stripping tags, so `&lt;i&gt;` survives the regex then renders as literal `<i>`. | `_clean("&lt;i&gt;x&lt;/i&gt;")` → `"<i>x</i>"`; seen as `<i>Hugo Barra</i>` in PDF. `translate.py:11-13` | med | trivial |
| 1 | 2 | **Vocab glosses wrong** — opus-mt translates single words as full sentences / hallucinations. Answer key teaches wrong meanings. | 茸→"I'll take care of it" (=mushroom), スライム→"Slide", 内臓→"Immaculate", こと→"Oh my God", 殺す→"I'll kill you", 円→"Circle", 成る→"Total". `workbook.py:68 enrich()` | HIGH | med |
| 2 | 3 | **MT hallucinations** on short / non-sentence input. | 第1話→"Hugo Barra", 犬とチェンソー→"[man speaking native language] >>Hugo Barra:", many "(Laughter)"/"Coke"; bad digits 3804万→"38,440,000" (real 38,040,000). `translate.py:25` | HIGH | med |
| 4 | 4 | **Counter/number readings wrong** — fugashi defaults. | `1日`→ついたち (context = いちにち). number+counter unreliable. `language.py:_reading` | med-high | med |
| 5 | 5 | **POS extraction noise** — fragments enter word lists. | 因る in verbs (from によって), 滅 げん as noun (verb stem), katakana title チェンソーマン→チェン/ツー/マン, だいたい as noun. `language.py:extract_words` | med | med |
| 6 | 6 | **OCR garbage on stylized / vertical / display text** (titles, SFX, covers) poisons furigana + MT + vocab. | ソ→ツ, 拓→取, 揺→見, 世界→他界, 鬼才→検査. manga-ocr is bubble-trained. | med | mitigate (filter junk boxes) |
| 7 | 7 | **Reading-order heuristic** mis-orders complex / vertical layouts → wrong dialog sequence + wrong sequencing answers. | `pcleaner_runner.py:_reading_order` | med | med |
| 8 | 8 | **Exercises blank verb stems** → grammatically partial answers. | 撃た, 見つから, 聞き as fill answers. `exercises.py:87` | low | low |
| 9 | 9 | **Header overflow** on text-dense pages — list wraps to many tiny lines. | wb4 p1 (Code Geass cover) | low | low |
| 10 | 10 | **Print-parity doc vs reality** — `render.py` docstring claims even-padded front matter for double-sided facing pages; code doesn't pad, appends summary at end. | `render.py:1-7,164` | low | low-med |

## Out of scope (decided)
- **Series mixup** (SnK + Dungeon Meshi in one workbook): user error — two books built
  without resetting the webapp between them. Refresh between books. Ignore.
- **Furigana not overlaid on original panel**: intended — original panels stay untouched.

## Workflow
- Prefer existing OSS tools over hand-written language logic.
- For each bug: fix → test (scripts/output in `out/`, gitignored) → commit.
