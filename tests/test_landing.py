"""The hosted landing page for friend invites, and the setting that points friends at it."""
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kakao_talk import pages
from custom_components.kakao_talk.const import DOMAIN
from custom_components.kakao_talk.http import INVITE_DECLINED, INVITE_THANKS

from .conftest import CONFIG, TOKEN_URL, posts
from .test_invite import CODE, INVITE_STATE, from_internet  # noqa: F401  (fixture)
from .test_pages import sha

HOSTED = "https://kanemari.github.io/kakao_talk_notifier/invite-done.html"
ROOT = Path(pages.__file__).resolve().parents[2]
PAGE = (ROOT / "docs" / "invite-done.html").read_text(encoding="utf-8")


# ------------------------------------------------------------------ the page file
def test_the_page_file_is_up_to_date():
    """Run `python dev/build_landing_page.py` if this fails."""
    assert PAGE == pages.render_landing()
    assert "\r" not in PAGE
    assert (ROOT / "docs" / ".nojekyll").exists()


def test_the_policy_in_the_page_matches_its_one_style_and_one_script():
    style = re.findall(r"<style>(.*?)</style>", PAGE, re.S)
    script = re.findall(r"<script>(.*?)</script>", PAGE, re.S)
    assert style == [pages.STYLE] and script == [pages.LANDING_SCRIPT]
    policy = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', PAGE).group(1)
    assert "style-src " + sha(style[0]) in policy and "script-src " + sha(script[0]) in policy
    for rule in ("default-src 'none'", "img-src 'none'", "base-uri 'none'", "form-action 'none'"):
        assert rule in policy
    assert "unsafe" not in policy and "*" not in policy


def test_the_page_loads_nothing_and_links_nowhere():
    assert not re.search(r"\b(src|href|action|srcset|poster|data)\s*=", PAGE)
    assert not re.search(r"https?://", PAGE)
    assert not re.search(r"\bon[a-z]+\s*=", PAGE)
    for tag in ("<iframe", "<form", "<link", "<img", "<object", "<embed", "<base"):
        assert tag not in PAGE
    assert 'name="referrer" content="no-referrer"' in PAGE
    assert 'name="robots" content="noindex,nofollow"' in PAGE


def test_the_page_has_three_fixed_states_and_only_the_neutral_one_shows_without_scripts():
    sections = re.findall(r'<section id="(\w+)"( hidden)?>', PAGE)
    assert sections == [("neutral", ""), ("relay", " hidden"), ("declined", " hidden")]


def test_the_script_only_picks_a_block_and_clears_the_address():
    script = pages.LANDING_SCRIPT
    assert "history.replaceState(null,'',location.pathname)" in script
    # the code is shown only if it is plain URL-safe text, and only as text
    assert "/^[A-Za-z0-9_-]{10,512}$/.test(c)" in script
    assert "getElementById('code').textContent=c" in script
    for forbidden in ("innerHTML", "outerHTML", "insertAdjacent", "document.write", "eval", "fetch",
                      "XMLHttpRequest", "sendBeacon", "window.open", "location.href", "location.replace",
                      "localStorage", "cookie"):
        assert forbidden not in script
    # the only thing it does with the code besides showing it is the Copy button
    assert script.count("c)") >= 1 and "navigator.clipboard.writeText(c)" in script


def test_the_page_says_the_same_as_the_pages_home_assistant_serves():
    assert pages.LANDING_TEXT["declined"][1] == INVITE_DECLINED
    assert pages.LANDING_TEXT["declined"][0] == "Permissions not accepted"
    # the hosted page cannot link anyone itself, so it asks the friend to send the code on
    assert pages.LANDING_TEXT["relay"][0] == "One more step"
    assert "Send this code to the person who invited you" in pages.LANDING_TEXT["relay"][1]
    assert INVITE_THANKS  # (the page Home Assistant serves after it has linked them itself)


# ------------------------------------------------------------------ the setting
async def hosted_entry(hass, **extra):
    await hass.async_add_executor_job(lambda: open(hass.config.path("kakao.session"), "w").write("rt"))
    e = MockConfigEntry(domain=DOMAIN, data={**CONFIG, "invite_redirect_uri": HOSTED, **extra}, title="K")
    e.add_to_hass(hass)
    assert await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    return e


async def test_the_invite_link_sends_friends_to_the_hosted_page(hass, kakao_api):
    await hosted_entry(hass)
    res = await hass.services.async_call(DOMAIN, "friend_invite_link", blocking=True, return_response=True)
    q = parse_qs(urlparse(res["url"]).query)
    assert q["redirect_uri"] == [HOSTED]  # exactly as entered: Kakao needs an exact match
    assert q["state"] == [INVITE_STATE]


async def test_your_own_login_still_returns_to_home_assistant(hass, kakao_api):
    await hosted_entry(hass)
    res = await hass.services.async_call(DOMAIN, "login", blocking=True, return_response=True)
    assert parse_qs(urlparse(res["url"]).query)["redirect_uri"] == ["http://192.168.1.10:8123/api/kakao_talk"]


async def test_a_hosted_page_means_home_assistant_answers_nothing_from_the_internet(
    hass, kakao_api, hass_client, from_internet
):
    await hosted_entry(hass)
    cfg = hass.data[DOMAIN]["config"]
    assert cfg.invite_uses_hosted_page and not cfg.invite_is_public
    client = await hass_client()
    for query in (
        f"?code=c&state={INVITE_STATE}",  # even a friend invite return is refused here
        f"?error=access_denied&state={INVITE_STATE}",
        "",
        "?code=c&state=forged",
        "?done=1",
    ):
        resp = await client.get("/api/kakao_talk" + query, allow_redirects=False)
        assert resp.status == 403, query
        assert await resp.text() == "Forbidden"
    assert posts(kakao_api, TOKEN_URL) == []


async def test_a_hosted_page_still_lets_you_finish_things_at_home(hass, kakao_api, hass_client):
    await hosted_entry(hass)
    client = await hass_client()
    resp = await client.get(f"/api/kakao_talk?code={CODE}&state={INVITE_STATE}")
    assert resp.status == 200 and "Your permission was recorded" in await resp.text()
    assert (await client.get("/api/kakao_talk")).status == 200


async def test_a_bare_address_still_means_your_own_home_assistant(hass, kakao_api):
    await hosted_entry(hass, invite_redirect_uri="https://ha.example.com")
    cfg = hass.data[DOMAIN]["config"]
    assert cfg.invite_is_public and not cfg.invite_uses_hosted_page
    assert cfg.invite_redirect_uri() == "https://ha.example.com/api/kakao_talk"


async def test_nothing_set_means_the_local_address(hass, kakao_api):
    await hosted_entry(hass, invite_redirect_uri="")
    cfg = hass.data[DOMAIN]["config"]
    assert not cfg.invite_is_public and not cfg.invite_uses_hosted_page
    assert cfg.invite_redirect_uri() == "http://192.168.1.10:8123/api/kakao_talk"


async def test_the_settings_form_accepts_a_page_and_rejects_bad_addresses(hass, entry):
    async def save(value):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        return await hass.config_entries.options.async_configure(
            result["flow_id"], {**CONFIG, "invite_redirect_uri": value}
        )

    assert (await save("http://example.com/done.html"))["errors"] == {"invite_redirect_uri": "https_required"}
    assert (await save(HOSTED + "?x=1"))["errors"] == {"invite_redirect_uri": "invalid_url"}
    assert (await save(HOSTED + "#top"))["errors"] == {"invite_redirect_uri": "invalid_url"}
    assert (await save("not a url"))["errors"] == {"invite_redirect_uri": "invalid_url"}
    ok = await save(HOSTED)
    assert ok["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.data["invite_redirect_uri"] == HOSTED


def test_the_setting_is_labelled_for_what_it_is():
    import json

    import custom_components.kakao_talk as component

    base = Path(component.__file__).parent
    for name in ("strings.json", "translations/en.json"):
        data = json.loads((base / name).read_text(encoding="utf-8"))
        for section in (data["config"]["step"]["user"], data["options"]["step"]["init"]):
            assert section["data"]["invite_redirect_uri"] == "Friend invite landing page"



def test_the_publish_script_puts_only_the_page_on_the_gh_pages_branch():
    script = (ROOT / "dev" / "publish_landing_page.sh").read_text(encoding="utf-8")
    assert "gh-pages" in script
    copied = re.findall(r"^cp .*$", script, re.M)
    assert copied == ['cp "$ROOT/docs/invite-done.html" invite-done.html']
    assert ": > .nojekyll" in script
    assert "git rm -rq" in script  # everything else on the branch is removed first
    assert "push -q origin gh-pages" in script and "origin main" not in script
