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
:root{color-scheme:light dark;--bg:#fee500;--card:#ffffff;--ink:#3c1e1e;--muted:#6f5c5c;--shadow:rgba(60,30,30,.28);--code:#f3efd0}
@media (prefers-color-scheme:dark){:root{--bg:#1e1c12;--card:#2b2920;--ink:#fee500;--muted:#cbc4a4;--shadow:rgba(0,0,0,.5);--code:#3a3727}}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans KR",sans-serif}
main{background:var(--card);border-radius:26px;max-width:420px;width:100%;padding:36px 28px 28px;text-align:center;box-shadow:0 10px 34px var(--shadow)}
.icon{width:92px;height:92px;display:block;margin:0 auto}
.badge{width:30px;height:30px;display:block;margin:20px auto 0}
.badge circle{fill:var(--ink)}
.badge path{stroke:var(--card)}
h1{font-size:1.55rem;line-height:1.25;margin:12px 0 8px}
p{margin:0;color:var(--muted);overflow-wrap:anywhere}
[hidden]{display:none!important}
code{display:block;margin:16px 0 4px;padding:12px;border-radius:12px;background:var(--code);color:var(--ink);font:13px/1.4 ui-monospace,Menlo,Consolas,monospace;word-break:break-all;user-select:all;text-align:left}
button{margin-top:12px;border:0;border-radius:999px;padding:10px 22px;background:var(--ink);color:var(--card);font:inherit;font-weight:600;cursor:pointer}
.note{margin-top:12px;font-size:.85rem}
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


def csp_for(document):
    """A Content-Security-Policy for a static page of ours (the setup page).

    Allows exactly the inline style and script blocks the document contains, by
    hash, and nothing else. The document must use "\n" line ends, as browsers
    hash the text after normalising them.
    """
    import re

    styles = re.findall(r"<style>(.*?)</style>", document, re.S)
    scripts = re.findall(r"<script>(.*?)</script>", document, re.S)
    return "; ".join(
        (
            "default-src 'none'",
            "style-src " + (" ".join(_hash(s) for s in styles) or "'none'"),
            "script-src " + (" ".join(_hash(s) for s in scripts) or "'none'"),
            "img-src 'none'",
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
        )
    )


# The static landing page for friends (hosted on GitHub Pages, see docs/invite-done.html).
# Kakao sends a friend there after they agree: ?code=... or ?error=... say which. Kakao links
# a friend to the app only when that code is exchanged for a token, which needs the Client
# secret, so a static page cannot do it: it shows the code (only if it is plain URL-safe
# text, and only as text) for the friend to send to the owner, who runs kakao_talk.link_friend.
# Then it removes the query from the address.
LANDING_SCRIPT = (
    "var p=new URLSearchParams(location.search),c=p.get('code'),"
    "s=p.has('error')?'declined':(c&&/^[A-Za-z0-9_-]{10,512}$/.test(c))?'relay':'neutral';"
    "['neutral','relay','declined'].forEach(function(i){"
    "document.getElementById(i).hidden=i!==s});"
    "if(s==='relay'){document.getElementById('code').textContent=c;"
    "document.getElementById('copy').addEventListener('click',function(){"
    "var b=this;navigator.clipboard.writeText(c).then("
    "function(){b.textContent='Copied'},"
    "function(){b.textContent='Select the code and copy it'})})}"
    "history.replaceState(null,'',location.pathname)"
)
LANDING_TEXT = {
    "relay": (
        "One more step",
        "Send this code to the person who invited you, for example in KakaoTalk. "
        "It works once and only for a short time, so send it now.",
    ),
    "declined": (
        "Permissions not accepted",
        "Permissions were not accepted. If you want to try again, ask the person who "
        "invited you for the link and open it once more.",
    ),
    "neutral": (
        "KakaoTalk Notifier",
        "This is the page friends see after they agree in Kakao. There is nothing to do here.",
    ),
}
LANDING_NOTE = "Do not share it anywhere else."


def landing_csp():
    """The policy for the static page, as a <meta> tag (a static host cannot set headers)."""
    return "; ".join(
        (
            "default-src 'none'",
            "style-src " + _hash(STYLE),
            "script-src " + _hash(LANDING_SCRIPT),
            "img-src 'none'",
            "base-uri 'none'",
            "form-action 'none'",
        )
    )


def render_landing():
    """The static landing page for friends: three fixed blocks, one of which the script shows."""

    def block(name, badge, extra=""):
        title, message = LANDING_TEXT[name]
        hidden = "" if name == "neutral" else " hidden"
        return (
            f'<section id="{name}"{hidden}>{badge}'
            f"<h1>{html.escape(title, quote=True)}</h1>"
            f"<p>{html.escape(message, quote=True)}</p>{extra}</section>"
        )

    relay_extra = (
        '<code id="code"></code><button id="copy" type="button">Copy code</button>'
        f'<p class="note">{html.escape(LANDING_NOTE, quote=True)}</p>'
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow">'
        '<meta name="referrer" content="no-referrer">'
        f'<meta http-equiv="Content-Security-Policy" content="{landing_csp()}">'
        "<title>KakaoTalk Notifier</title>"
        "<style>" + STYLE + "</style></head><body><main>"
        + ICON
        + block("neutral", "")
        + block("relay", BADGE_OK, relay_extra)
        + block("declined", BADGE_PROBLEM)
        + '<div class="brand">KakaoTalk Notifier</div>'
        "</main><script>" + LANDING_SCRIPT + "</script></body></html>\n"
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
