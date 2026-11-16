import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kakao_talk.const import DOMAIN

CONFIG = {
    "api_key": "rest-key",
    "client_secret": "secret",
    "redirect_uri": "http://192.168.1.10:8123",
    "button_title": "View",
    "send_to_friends": True,
    "friends": [],
}

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
FRIENDS_URL = "https://kapi.kakao.com/v1/api/talk/friends"
FRIENDS_SEND_URL = "https://kapi.kakao.com/v1/api/talk/friends/message/default/send"
UPLOAD_URL = "https://kapi.kakao.com/v2/api/talk/message/image/upload"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def kakao_api(aioclient_mock):
    """Mock the Kakao endpoints; returns the mock for call inspection."""
    aioclient_mock.post(TOKEN_URL, json={"access_token": "at", "refresh_token": "rt"})
    aioclient_mock.post(MEMO_URL, json={"result_code": 0})
    aioclient_mock.post(FRIENDS_SEND_URL, json={"successful_receiver_uuids": []})
    aioclient_mock.post(
        UPLOAD_URL,
        json={"infos": {"original": {"url": "https://k.kakaocdn.net/uploaded.png"}}},
    )
    aioclient_mock.get(
        FRIENDS_URL,
        json={
            "total_count": 2,
            "elements": [
                {"uuid": "u-alice", "profile_nickname": "Alice"},
                {"uuid": "u-bob", "profile_nickname": "Bob"},
            ],
        },
    )
    return aioclient_mock


@pytest.fixture
async def entry(hass, kakao_api):
    """A set-up config entry that is already logged in."""
    await hass.async_add_executor_job(
        lambda: open(hass.config.path("kakao.session"), "w").write("rt")
    )
    entry = MockConfigEntry(domain=DOMAIN, data=dict(CONFIG), title="KakaoTalk")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def posts(mock, url):
    """Form bodies POSTed to url."""
    return [c[2] for c in mock.mock_calls if c[0] == "POST" and str(c[1]) == url]


@pytest.fixture(autouse=True)
def clean_session_file(hass):
    """The test config dir is shared between tests; never leak a login between them."""
    import os

    path = hass.config.path("kakao.session")
    if os.path.exists(path):
        os.remove(path)
    yield
    if os.path.exists(path):
        os.remove(path)
