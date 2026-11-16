# Testing

## Automated tests (no Kakao account needed)

Real Home Assistant, with the Kakao API mocked.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
pytest
```

They cover the UI setup and options flows, the YAML import and its deprecation notice,
single-instance, per-message `friends` / `send_to_friends` / `send_to_me`, URL and media
image sending, `list_friends`, `notify.kakao_talk`, and unloading.

They do **not** prove that Kakao accepts the requests, in particular the image-upload
endpoint. That needs the manual test below.

## Manual test with a real Home Assistant

```bash
cd dev && docker compose up
```

Open http://localhost:8123, finish onboarding, then:

1. **Settings > Devices & services > Add integration > KakaoTalk Notifier** and enter your
   Kakao app settings. Register `http://localhost:8123/api/kakao_talk` as a Redirect URI at
   Kakao (and use `http://localhost:8123` as the Home Assistant address).
2. Run `kakao_talk.login` from Developer tools > Actions and open the link.
3. Work through the blocks in [developer-tools-test.md](developer-tools-test.md).
4. To test the migration, stop the container, delete `dev/config/.storage/core.config_entries`
   entry for kakao_talk (or the whole `dev/config` folder), uncomment the `kakao_talk:` block
   in `dev/config/configuration.yaml`, and start again. The settings should appear in the UI
   and a repair notice should ask you to remove the YAML.
