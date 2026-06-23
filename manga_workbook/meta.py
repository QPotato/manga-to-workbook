"""Provenance metadata embedded in each workbook for debugging/reproducibility.

Captures what produced a given PDF: the git commit, the RNG seed driving the
exercise shuffles (the chapter name — see exercises.py), the run settings, and
the host environment. Stored on the workbook dict, so it lands in both
workbook.json and the rendered PDF's "Build info" colophon.
"""
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def _git(*args):
    try:
        out = subprocess.run(
            ["git", "-C", str(_REPO), *args],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def git_commit():
    """Short commit hash, suffixed '+dirty' when the tree has uncommitted changes."""
    h = _git("rev-parse", "--short", "HEAD")
    if not h:
        return "unknown"
    return f"{h}+dirty" if _git("status", "--porcelain") else h


def build_meta(settings):
    """Provenance block for the workbook: commit, seed, settings, environment.

    `settings` is the run configuration (chapter, pages, with_llm, model, reuse);
    the exercise RNG seed is the chapter name, recorded explicitly under `seed`.
    """
    settings = dict(settings)
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": git_commit(),
        "seed": settings.get("chapter"),
        "settings": settings,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def footer_html(meta) -> str:
    """A small, unobtrusive build-info footer for the generated static webpages.

    Two lines: the *build* provenance carried over from workbook.json (commit,
    seed, settings, environment — same as the PDF colophon), and the *render*
    stamp captured now, when this HTML is written. The two commits differ when a
    reader/practice page is regenerated from an older workbook.json on a newer
    checkout, so a stray file can always be traced back to both builds.
    """
    rows = []
    if meta:
        s = meta.get("settings", {})
        llm = str(s.get("model")) if s.get("with_llm") else "off"
        bits = [
            f'commit {_esc(meta.get("commit", "?"))}',
            f'seed {_esc(meta.get("seed", ""))}',
            f'{_esc(s.get("pages", "?"))} pages',
            f'LLM {_esc(llm)}',
            f'python {_esc(meta.get("python", "?"))}',
            _esc(meta.get("platform", "")),
            _esc(meta.get("generated", "")),
        ]
        rows.append('build · ' + ' · '.join(b for b in bits if b))
    rows.append(
        'page rendered · commit ' + _esc(git_commit()) + ' · '
        + _esc(datetime.now(timezone.utc).isoformat(timespec="seconds")))
    body = '<br>'.join(rows)
    return (
        '<footer class="build-info" style="max-width:1100px;margin:28px auto 12px;'
        'padding:8px 14px;border-top:1px solid #e2e2e2;color:#aaa;'
        'font-family:Consolas,\'Courier New\',monospace;font-size:11px;line-height:1.6;'
        'word-break:break-all">'
        'manga-to-workbook<br>' + body +
        '</footer>'
    )
