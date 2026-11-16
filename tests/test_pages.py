"""The themed pages: fixed markup, escaped text, strict Content-Security-Policy."""
import base64
import hashlib
import re

import pytest

from custom_components.kakao_talk import pages
from custom_components.kakao_talk.const import DOMAIN

from .test_invite import INVITE_STATE, from_internet, public_entry  # noqa: F401  (fixtures)


def sha(text):
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"


def test_text_is_escaped():
    out = pages.render('<b>"x"</b>', "<script>alert(1)</script> & 'q'")
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &#x27;q&#x27;" in out
    assert "<h1>&lt;b&gt;&quot;x&quot;&lt;/b&gt;</h1>" in out


def test_exactly_one_script_and_one_style_and_hashes_match_them():
    out = pages.render("t", "m")
    scripts = re.findall(r"<script>(.*?)</script>", out, re.S)
    styles = re.findall(r"<style>(.*?)</style>", out, re.S)
    assert scripts == [pages.SCRIPT] and styles == [pages.STYLE]
    assert "script-src " + sha(scripts[0]) in pages.CSP
    assert "style-src " + sha(styles[0]) in pages.CSP


def test_csp_blocks_everything_else():
    csp = pages.CSP
    for rule in ("default-src 'none'", "img-src 'none'", "base-uri 'none'", "form-action 'none'", "frame-ancestors 'none'"):
        assert rule in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp and "*" not in csp


def test_no_external_resources_links_or_event_handlers():
    out = pages.render("t", "m")
    assert not re.search(r"\b(src|href|action|srcset|poster|data)\s*=", out)
    assert not re.search(r"https?://", out)
    assert not re.search(r"\bon[a-z]+\s*=", out)
    assert "url(" not in out and "@import" not in out
    assert "<iframe" not in out and "<form" not in out and "<link" not in out


def test_page_is_themed_and_responsive():
    out = pages.render("Thank you", "m")
    assert 'viewBox="0 0 128 128"' in out and "#fee500" in out and "#3c1e1e" in out
    assert "prefers-color-scheme:dark" in out
    assert 'name="viewport"' in out and 'name="robots" content="noindex,nofollow"' in out
    assert "<title>KakaoTalk Notifier</title>" in out


def test_problem_and_ok_badges_differ():
    assert pages.render("t", "m", ok=True) != pages.render("t", "m", ok=False)


def test_script_only_removes_the_query_from_the_address():
    assert pages.SCRIPT == "history.replaceState(null,'',location.pathname)"


# ------------------------------------------------------------------ over HTTP
async def test_thank_you_response_headers(hass, public_entry, hass_client, from_internet):
    client = await hass_client()
    resp = await client.get(f"/api/kakao_talk?code=c&state={INVITE_STATE}")
    assert resp.status == 200
    assert resp.headers["Content-Security-Policy"] == pages.CSP
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert resp.headers["Content-Type"].startswith("text/html")
    assert "Access-Control-Allow-Origin" not in resp.headers


async def test_nothing_from_the_request_reaches_a_public_page(hass, public_entry, hass_client, from_internet):
    client = await hass_client()
    bait = "Zq9-bait-text-0100"
    for query in (
        f"?code={bait}&state={INVITE_STATE}",
        f"?code=c&state={INVITE_STATE}&error_description={bait}&x={bait}",
        f"?error={bait}&error_description={bait}&state={INVITE_STATE}",
    ):
        resp = await client.get("/api/kakao_talk" + query)
        assert resp.status == 200
        assert bait not in await resp.text()


async def test_forbidden_stays_bare_text(hass, entry, hass_client, from_internet):
    client = await hass_client()
    resp = await client.get("/api/kakao_talk")
    assert resp.status == 403
    assert await resp.text() == "Forbidden"
    assert resp.headers["Content-Type"].startswith("text/plain")


async def test_local_error_text_is_escaped_in_the_page(hass, entry, hass_client):
    res = await hass.services.async_call(DOMAIN, "login", blocking=True, return_response=True)
    state = res["url"].split("state=")[1].split("&")[0]
    client = await hass_client()
    resp = await client.get(
        "/api/kakao_talk", params={"error": "x", "error_description": "<b>bold</b>", "state": state}
    )
    body = await resp.text()
    assert "<b>bold</b>" not in body and "&lt;b&gt;bold&lt;/b&gt;" in body


async def test_setup_page_is_themed(hass, entry, hass_client):
    client = await hass_client()
    body = await (await client.get("/api/kakao_talk")).text()
    assert "viewBox=\"0 0 128 128\"" in body and "prefers-color-scheme: dark" in body
    assert "kakao_talk.login" in body  # the instructions are still there


# ------------------------------------------------------------------ setup page policy
def test_csp_for_hashes_every_inline_block():
    doc = "<html><style>a{b:c}</style><p>x</p><script>one()</script><script>two()</script></html>"
    csp = pages.csp_for(doc)
    assert "style-src " + sha("a{b:c}") in csp
    assert "script-src " + sha("one()") + " " + sha("two()") in csp
    assert "default-src 'none'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp
    assert "script-src 'none'" in pages.csp_for("<p>nothing</p>")


async def test_setup_page_has_a_strict_policy_matching_its_content(hass, entry, hass_client):
    client = await hass_client()
    resp = await client.get("/api/kakao_talk")
    body = await resp.text()
    assert "\r" not in body  # line ends are normalised, as the hashes are of that text
    csp = resp.headers["Content-Security-Policy"]
    for block in re.findall(r"<style>(.*?)</style>", body, re.S) + re.findall(r"<script>(.*?)</script>", body, re.S):
        assert sha(block) in csp
    assert "default-src 'none'" in csp and "unsafe-inline" not in csp
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
