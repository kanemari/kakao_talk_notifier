"""The small themed pages shown after a Kakao login or friend invite.

Everything is fixed markup in one file: no external fonts, images or scripts. Text that
is put into a page is escaped, and a strict Content-Security-Policy (with hashes of the
one style block and the one script) stops the browser from running or loading anything
else, so even a bug here could not turn a page into a way to run code.

This module has no Home Assistant imports, so it can be rendered and tested on its own.
"""
import base64
import hashlib
import html

# The project icon (docs/icon.svg), inline so the page needs no other file.
ICON = (
    '<svg class="icon" viewBox="0 0 128 128" role="img" aria-label="KakaoTalk Notifier">'
    '<rect width="128" height="128" rx="28" fill="#fee500"/>'
    '<g transform="translate(64 61.6) scale(1.22) translate(-64 -61)">'
    '<path d="M24 38a14 14 0 0 1 14-14h52a14 14 0 0 1 14 14v36a14 14 0 0 1-14 14H62L42 106V88h-4a14 14 0 0 1-14-14z" fill="#3c1e1e"/>'
    '<path d="M64 38 41 58h7v18h12V64h8v12h12V58h7z" fill="#fee500" stroke="#fee500" stroke-width="3" stroke-linejoin="round"/>'
    '<circle cx="98" cy="30" r="12" fill="#ff6b5e" stroke="#fee500" stroke-width="5"/>'
    "</g></svg>"
)

BADGE_OK = (
    '<svg class="badge" viewBox="0 0 24 24" aria-hidden="true">'
    '<circle cx="12" cy="12" r="12"/>'
    '<path d="M7 12.5l3.2 3.2L17 8.8" fill="none" stroke-width="2.4" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)
BADGE_PROBLEM = (
    '<svg class="badge" viewBox="0 0 24 24" aria-hidden="true">'
    '<circle cx="12" cy="12" r="12"/>'
    '<path d="M12 6.8v6.4M12 16.6v.4" fill="none" stroke-width="2.6" stroke-linecap="round"/></svg>'
)

STYLE = """
:root{color-scheme:light dark;--bg:#fee500;--card:#ffffff;--ink:#3c1e1e;--muted:#6f5c5c;--shadow:rgba(60,30,30,.28)}
@media (prefers-color-scheme:dark){:root{--bg:#1e1c12;--card:#2b2920;--ink:#fee500;--muted:#cbc4a4;--shadow:rgba(0,0,0,.5)}}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans KR",sans-serif}
main{background:var(--card);border-radius:26px;max-width:420px;width:100%;padding:36px 28px 28px;text-align:center;box-shadow:0 10px 34px var(--shadow)}
.icon{width:92px;height:92px;display:block;margin:0 auto}
.badge{width:30px;height:30px;display:block;margin:20px auto 0}
.badge circle{fill:var(--ink)}
.badge path{stroke:var(--card)}
h1{font-size:1.55rem;line-height:1.25;margin:12px 0 8px}
p{margin:0;color:var(--muted);overflow-wrap:anywhere}
.brand{margin-top:26px;font-size:.78rem;letter-spacing:.05em;color:var(--muted);opacity:.85}
"""

# Replaces the address in the browser (and its history entry) with the bare path, so a
# one-time code Kakao put in the address does not stay visible there.
SCRIPT = "history.replaceState(null,'',location.pathname)"


def _hash(text):
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


CSP = "; ".join(
    (
        "default-src 'none'",
        "style-src " + _hash(STYLE),
        "script-src " + _hash(SCRIPT),
        "img-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    )
)


def render(title, message, ok=True):
    """The page for a title and a message (both are escaped). Returns the HTML text."""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow">'
        "<title>KakaoTalk Notifier</title>"
        "<style>" + STYLE + "</style></head><body><main>"
        + ICON
        + (BADGE_OK if ok else BADGE_PROBLEM)
        + "<h1>" + html.escape(str(title), quote=True) + "</h1>"
        "<p>" + html.escape(str(message), quote=True) + "</p>"
        '<div class="brand">KakaoTalk Notifier</div>'
        "</main><script>" + SCRIPT + "</script></body></html>"
    )
