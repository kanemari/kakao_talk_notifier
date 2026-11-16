# Changelog

## Unreleased

### Added

* **Friend invite link**: the new `kakao_talk.friend_invite_link` action (administrators
  only) gives you a link to send to a friend. They open it, sign in to Kakao and agree to
  the friends and message permissions, instead of having to use the Kakao console's REST API
  test. The link cannot start, replace or complete a login. See
  [Sending to friends](README.md#sending-to-friends).
* **Pick friends by name**: every friend Kakao returns becomes a notify entity ("KakaoTalk
  Alice"), and `kakao_talk.send_message` has a **Targets** picker listing them, instead of
  typing names or looking them up with `list_friends`. Home Assistant's `notify.send_message`
  can target them too. Friends who leave become unavailable. The typed `friends` field still
  works. See [Picking friends by name](README.md#picking-friends-by-name).
* **Public address for friend invites** (optional setting): friends away from home are sent
  back to a public address of your Home Assistant and see a thank-you page, instead of a
  "page cannot be loaded" error. It must be an `https://` address. From the internet only
  that fixed thank-you text is answered, and only when this setting is filled in; every
  other request is still refused.

* **Themed pages**: the pages shown after a Kakao login or friend invite (thank-you, permissions
  not accepted, login errors) and the setup page now use the project icon and colours, in light and
  dark. The public ones are fixed markup with no external files, escape any text they show, and
  carry a strict Content-Security-Policy. The thank-you page also removes Kakao's one-time code
  from the browser's address bar.

### Security

* A completed Kakao login now creates a "KakaoTalk login completed" notification, so an
  unexpected login is noticed.
* Friend invites require a Client secret, so a friend's one-time code is useless to anyone
  who sees the address of the page they are sent back to.
* Pages that can be reached from the internet show fixed text only, never anything taken
  from the request.
* The login error page shows Kakao's error text only for a login an administrator started;
  otherwise it shows a fixed message, so a web page cannot make it display its own words.
* The setup page is served with the same strict Content-Security-Policy as the other pages.
* Blocked requests from the internet are logged as a warning at most once every 10 minutes,
  so the log cannot be flooded.
* An image is checked for size before it is read, and requests to Kakao time out after 30
  seconds.
* The README has a full description of what `/api/kakao_talk` does and which risks remain.

## 2026.11.16.3 - 2026-11-16

Everything since the last stable release, 2026.11.16.1.

### Before you upgrade

* **Home Assistant 2025.7 or newer is now required** (the image picker needs it).
* **Setup moved to the UI.** Your `kakao_talk:` block in `configuration.yaml` is imported
  automatically on the first start, once. Home Assistant then shows a repair notice asking
  you to remove the `kakao_talk:` block and the `- platform: kakao_talk` entry under
  `notify:` yourself, then restart. Your login is kept. See
  [Migrating from configuration.yaml](README.md#migrating-from-configurationyaml-deprecated).
* **Sending while logged out now fails with an error** ("Could not sign in to KakaoTalk")
  instead of silently doing nothing. Automations that relied on the silent behaviour will
  now show an error; run `kakao_talk.login` to fix the cause.
* **Mistakes in a call** (both `url` and `image`, both targets off, an unknown friend, a
  bad image) are now reported as validation errors (HTTP 400), not as server errors.

### Added

* **UI configuration**: set up and change every setting under *Settings > Devices &
  services*, including a friend picker. Only one instance can be set up.
* **Per-message recipients**: `friends`, `send_to_friends` and `send_to_me` on
  `kakao_talk.send_message` and in the `data` of `notify.kakao_talk`, so you can message
  only chosen friends and skip your own copy.
* **Images from your media**: the `image` field uploads a JPEG or PNG (up to 5 MB) from
  Local media to Kakao, using the media picker in the Actions form.
* **Choose what a tap opens**:
  * *Open the image when tapped* (setting `link_to_image`, also per message): tapping an
    image message opens the image.
  * `link_url` per message: open any address.
  * If Kakao refuses a message because of its link, it is sent once more with the normal
    link, so the notification still arrives.
  * Set **Button link address** to a harmless page on a registered domain (for example
    `https://developers.kakao.com`) so that no tap opens Home Assistant. See
    [What a tap opens](README.md#what-a-tap-opens).
* **Debug logging** of every message's type, tap link and button label
  (`Kakao send to me: type=... link=...`).
* **Test material** (not part of the install): 76 automated tests that run against a real
  Home Assistant with Kakao mocked, a Docker test runner (`dev/run-tests.sh`), a dev Home
  Assistant, and a Developer tools test guide.

### Changed

* Clearer error when an image cannot be uploaded: it names the media source and explains
  that only Local media (*Media > My media*) works, and what to do instead.
* Documentation: Kakao setup lists which web domains to register, new sections *What a tap
  opens*, *Avoiding Home Assistant on tap* and *Debug logging*, and more troubleshooting.
* The integration icon is the project's own artwork (a bigger, centred speech bubble),
  shown by Home Assistant 2026.3 and newer. The README now has a header icon and a note
  that the project is unofficial.
* Removed the old example images and legacy graphics from the repository.

### Fixed

* The **Image** field of `kakao_talk.send_message` was greyed out in the Actions form; it
  now accepts JPEG and PNG and can be used.

### Security

* Text returned by Kakao in the login callback is cleaned and length-limited before it is
  logged or shown, plain-text responses are sent with `X-Content-Type-Options: nosniff`, and
  unexpected non-object replies from Kakao are handled instead of causing errors.
