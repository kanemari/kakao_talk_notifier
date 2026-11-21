<p align="center">
  <img src="docs/icon.svg" width="96" alt="KakaoTalk Notifier icon">
</p>

<h1 align="center">KakaoTalk Notifier</h1>

A [Home Assistant][hass] custom integration that sends notifications to KakaoTalk:
to your own "My Chatroom", and optionally to Kakao Talk friends.

Unofficial project, not affiliated with or endorsed by Kakao Corp. KakaoTalk and Kakao are
trademarks of their owners.

Originally based on the `kakao_talk` integration by musk95 and clipman, now substantially
rewritten (MIT licensed, see [LICENSE](LICENSE)).

See the [changelog](CHANGELOG.md) for what changed in each version.

Good to know before you start:

* Messages to yourself arrive in "My Chatroom" **silently**: no push notification and no
  unread badge. This is how Kakao delivers them.
* Kakao does not allow an app to post into group chats. Messages to other people are
  sent one-to-one (see [Sending to friends](#sending-to-friends)).

## Installation

Requires Home Assistant 2025.7 or newer (the image picker of `kakao_talk.send_message`
needs it).

With HACS:

1. Open the HACS menu and choose **Custom repositories**.
2. Add the repository below with the category **Integration**:
   ```
   https://github.com/kanemari/kakao_talk_notifier
   ```
3. Download **KakaoTalk Notifier** and restart Home Assistant.

## Kakao setup

In the Kakao Developers console (https://developers.kakao.com/), create an app, then:

1. **Kakao Login > General**: turn Kakao Login **ON**.
2. **App > Platform Key > REST API key**: copy the **REST API key**. On the same page,
   copy the **Client secret** if it is enabled (it is by default).
3. **App > Platform Key > REST API key > Redirect URI**: register your Home Assistant
   address plus `/api/kakao_talk`, for example:
   ```
   http://192.168.1.10:8123/api/kakao_talk
   ```
   Use the **local** address of Home Assistant. It must match the Home Assistant address (`redirect_uri`) you enter in the integration exactly.
4. **Kakao Login > Consent items > Access permission**: set **Send Kakao Talk Message**
   (`talk_message`) to *Optional consent*.
5. **App > Product Link > Web domain**: register the domains your messages link to.
   Every message carries a link, and Kakao may refuse or replace links on domains that are
   not registered. Which domains you need depends on what a tap should open (see
   [What a tap opens](#what-a-tap-opens)):
   * your Home Assistant address, if you keep the default link;
   * a harmless page such as `https://developers.kakao.com`, if taps should **not** open
     Home Assistant;
   * `https://k.kakaocdn.net`, to open an image uploaded from the picker when it is tapped;
   * the domain of your own image addresses, to open an image given with `url:`.

## Configuration

Set it up from the UI: **Settings > Devices & services > Add integration > KakaoTalk
Notifier**. Every setting can be changed later with **Configure** on the integration;
saving reloads it. No `notify:` entry is needed, since the integration provides
`notify.kakao_talk` itself.

| Setting | Required | Description |
|---|---|---|
| REST API key (`api_key`) | yes | The REST API key of your Kakao app. |
| Client secret (`client_secret`) | if enabled | The Client secret of the REST API key. Needed whenever Client secret is enabled in the Kakao console, which is the default. |
| Home Assistant address (`redirect_uri`) | yes | The local address of Home Assistant, as a full URL starting with `http://` or `https://`, without a path. Kakao sends your browser back to this address plus `/api/kakao_talk` after you log in. |
| Button link address (`link_url`) | no | The address a tapped message (and its button) opens. Defaults to the Home Assistant address. Its domain must be registered under *App > Product Link > Web domain*. To stop taps opening Home Assistant, see [Avoiding Home Assistant on tap](#avoiding-home-assistant-on-tap). |
| Friend invite landing page (`invite_redirect_uri`) | no | The `https://` page friends are sent to after they agree to a [friend invite](#sending-to-friends). Use the hosted page `https://kanemari.github.io/kakao_talk_notifier/invite-done.html` (recommended, nothing of yours is exposed), or a bare public address of your own Home Assistant. Register it as an extra Redirect URI at Kakao. Empty means your local Home Assistant address, which friends cannot open away from home. See [Friends away from home](#friends-away-from-home-optional). |
| Open the image when tapped (`link_to_image`) | no | Off by default. When on, tapping an image message opens the image instead of Home Assistant. See [What a tap opens](#what-a-tap-opens). |
| Button label (`button_title`) | no | The label of the button in a message. Defaults to `View`. |
| Also send to friends (`send_to_friends`) | no | Also sends every message to Kakao Talk friends. Off by default. See [Sending to friends](#sending-to-friends). |
| Create friends as entities (`friend_entities`) | no | On by default. Adds each friend as a notify entity so they can be picked by name under **Targets** in the Send message form, see [Picking friends by name](#picking-friends-by-name). Turn off if you do not want friends' names stored and visible to every Home Assistant user; you then type names instead. Only used when *Also send to friends* is on. |
| Friends to send to (`friends`) | no | Nicknames or uuids. When logged in with friends on, **Configure** offers the friends Kakao returns to pick from. Without any, every friend Kakao returns receives every message. |

### Migrating from configuration.yaml (deprecated)

Configuring through `configuration.yaml` is **deprecated** and will be removed in a future
release. If you still have it:

```yaml
kakao_talk:
  api_key: YOUR_REST_API_KEY
  ...
notify:
  - platform: kakao_talk
```

then on the first start with this version the settings are **imported into the UI
automatically** (once; afterwards the UI is the source of truth and the YAML values are
ignored). Home Assistant shows a repair notice asking you to delete the `kakao_talk:` block
and the `- platform: kakao_talk` entry under `notify:` yourself, then restart. The
integration does not edit your `configuration.yaml`, since it cannot do so safely
(comments, `!secret`, includes and packages). The notice disappears once they are gone.
Your login is kept: the `kakao.session` file is unchanged.

## Logging in

1. In Home Assistant, go to *Developer tools > Actions* and run **`kakao_talk.login`**
   as an administrator.
2. A notification appears with a single-use login link that expires in 10 minutes.
   Open it on a device on your home network.
3. Log in to Kakao and approve. You land on a page saying the login is complete.

Messages are sent as the account that logged in. To switch accounts, or after turning on
`send_to_friends`, run `kakao_talk.login` again. After a login the Home Assistant log
shows which permissions Kakao granted in the "KakaoTalk login completed" notification.

Opening `<redirect_uri>/api/kakao_talk` in a browser shows a short setup page. A login
cannot be started from that page.

## Sending notifications

### Text message

```yaml
actions:
  - action: notify.kakao_talk
    data:
      title: Front door
      message: The door has been open for 10 minutes.
```

* **message** (required): the message text.
* **title** (optional): shown above the message, separated by a blank line.

### Message with an image

```yaml
actions:
  - action: notify.kakao_talk
    data:
      title: Front door
      message: Someone is at the door.
      data:
        photo:
          - url: https://example.com/doorbell.jpg
```

* **url** (required for an image): the address of the image. Use one that is reachable
  from the internet, since the image is loaded by Kakao and by the recipient's phone,
  not by Home Assistant. The message is then sent as a card with the image, the title
  and the message. One message is sent per image.

### Message with an image from your media

Instead of a public URL you can pick an image from Home Assistant's media (for example
`/media`). It is uploaded to Kakao, so it need not be reachable from the internet.
JPEG or PNG, up to 5 MB. Only files in **Local media** (*Media > My media*) work; images
from a camera, an add-on or another media source cannot be uploaded, so copy the file
into My media first, or use a public `url:` instead.

```yaml
actions:
  - action: kakao_talk.send_message
    data:
      message: Someone is at the door.
      image:
        media_content_id: media-source://media_source/local/doorbell.jpg
        media_content_type: image/jpeg
```

### What a tap opens

Kakao requires every message to carry a link, so tapping a message (or its button) always
opens something. By default that is the **Button link address** (`link_url`), which
defaults to your Home Assistant address.

* **Open the image instead:** turn on *Open the image when tapped* under **Configure**,
  or set `link_to_image: true` on a single message. Tapping an image message then opens
  the image itself.
* **Open any address:** set `link_url` on a message, for example a camera page. It takes
  priority over `link_to_image`.

```yaml
actions:
  - action: kakao_talk.send_message
    data:
      message: Someone is at the door.
      url: https://example.com/doorbell.jpg
      link_to_image: true
```

Kakao only accepts links on domains you registered under **App > Product Link > Web
domain**, so register the domain the image is served from. If Kakao refuses the message
because of the link, the integration sends it once more with the normal link, so you still
get the notification (the log says so).

An image you upload with `image:` is hosted by Kakao at `k.kakaocdn.net`. Register
`https://k.kakaocdn.net` as a web domain and turn on *Open the image when tapped* (or set
`link_to_image: true`), and tapping the message opens that image.

#### Avoiding Home Assistant on tap

Kakao has no message without a link, so the link cannot be removed, but it does not have
to be Home Assistant. Set **Button link address** (`link_url`) under **Configure** to a
harmless page on a domain you registered at Kakao, for example
`https://developers.kakao.com`:

1. In the Kakao console, under *App > Product Link > Web domain*, add
   `https://developers.kakao.com`.
2. Under **Configure**, set **Button link address** to `https://developers.kakao.com`.

From then on every message opens that page when tapped, and nothing leads to Home
Assistant. It also becomes the fallback for *Open the image when tapped*. You can still
override it on a single message with `link_url`.

Kakao has no real image attachment, so an image message is a card: tapping it always opens
an address (in Kakao's in-app browser), never Kakao's own photo viewer.

If a tap still opens Home Assistant, turn on debug logging for `custom_components.kakao_talk`
and look at the line `Kakao send to me: type=... link=...`: it shows the exact link sent. If
that link is what you expect but Kakao opens something else, Kakao replaced a link whose
domain is not registered.

### Picking friends by name

With **Also send to friends** on and a login that includes the friends permission, every
friend Kakao returns appears in Home Assistant as a notify entity named after them, for
example **KakaoTalk Alice**, all under one device called *KakaoTalk*. They are added when you log in, when
you run `kakao_talk.list_friends`, and by a background check about once an hour.

* In the **`kakao_talk.send_message`** form, pick one or more friends under **Targets**. Only
  KakaoTalk friends are offered. Picking the *KakaoTalk* device means all friends. Areas,
  floors and labels are not supported (you get a clear error). Friends picked there are added
  to any names typed in the **Friends** field.
* Home Assistant's own `notify.send_message` can also target a friend entity, to send them a
  plain message (with an optional title) without writing YAML.
* A friend Kakao no longer returns becomes **unavailable**; they come back if Kakao returns
  them again. Entities are kept between restarts, so your automations do not break while
  Kakao is unreachable.
* Turning **Also send to friends** or **Create friends as entities** off removes the friend
  entities. You can still type names or Kakao IDs in the **Friends** field.

```yaml
actions:
  - action: kakao_talk.send_message
    target:
      entity_id:
        - notify.kakaotalk_alice
        - notify.kakaotalk_bob
    data:
      message: Dinner is ready.
      send_to_me: false
```

The friends' names and Kakao IDs are stored in Home Assistant's entity registry, which every
Home Assistant user can see.

### Choosing recipients per message

`kakao_talk.send_message` (and `data:` of `notify.kakao_talk`) accept:

* **friends**: nicknames or uuids to message, instead of the `friends:` list in the
  configuration. Run `kakao_talk.list_friends` to see the names and uuids.
* **send_to_friends**: override the configured setting for this message.
* **send_to_me**: set `false` to skip your own copy and message only the friends.

```yaml
actions:
  - action: kakao_talk.send_message
    data:
      message: Dinner is ready.
      friends: ["Alice"]
      send_to_me: false
```

These need *Also send to friends* turned on in the integration settings (so the login includes the
friends permission); see [Sending to friends](#sending-to-friends).

### Actions

| Action | What it does |
|---|---|
| `notify.kakao_talk` | Sends a notification (see the examples above). Home Assistant shows only its generic fields for `notify` actions, so put `photo`, `friends`, `send_to_friends`, `send_to_me`, `link_to_image` and `link_url` in the `data` field (YAML). Handy for existing notify setups. |
| `kakao_talk.send_message` | The same, called directly; the best choice from the UI, since it has a proper form (including the image picker and a friend picker under **Targets**), with the fields `message` (required), `title`, `url`, `image`, `link_to_image`, `link_url`, `friends`, `send_to_friends` and `send_to_me`. |
| `kakao_talk.login` | Starts a Kakao login. Administrators only. |
| `kakao_talk.link_friend` | Links a friend to your app with the code their landing page showed (administrators only). Needed with the hosted landing page; see [Enrolling each friend](#enrolling-each-friend). |
| `kakao_talk.friend_invite_link` | Returns a link to send to a friend so they can give their permission with a normal Kakao sign-in. Administrators only. See [Sending to friends](#sending-to-friends). |
| `kakao_talk.list_friends` | Returns the nicknames and uuids of the friends Kakao makes available to your app. |

## Sending to friends

Kakao only lets an app message friends one-to-one, and its Message API is meant for
messages a user sends themselves, not automated ones. Until Kakao approves the
"Kakao Talk friend list / message" additional feature for a business app, you can still
use it with a small group of testers. There is a one-time setup, then a short checklist
for each friend.

### One-time setup (you, the sender)

1. In the Kakao Developers console, under **Kakao Login > Consent items > Personal
   information**, set **Friends list in Kakao services** to *Consent during use*.
2. Make sure **Client secret** is turned on for your REST API key (it is by default) and
   that you entered it under **Configure** on the integration. Friend invites need it.
3. Under **Configure**, turn on **Also send to friends**.
4. Run `kakao_talk.login` (*Developer tools > Actions*) and log in as yourself, so that
   Kakao asks for the friends permission. Do this again whenever you change that setting.

### Enrolling each friend

Repeat this for every friend who should receive messages. The friend only has to do steps 2
and 5.

1. **You: invite their Kakao account.** In the Kakao Developers console, under
   **App > Member**, invite the friend by the email address they use to log in to Kakao.
2. **Friend: sign in to Kakao Developers.** They open https://developers.kakao.com/ and
   sign in with that Kakao account, creating a developer account if they have none. Your
   app should then appear in their app list. Kakao may also send an invitation message,
   but they do not need to wait for it.
3. **Check the basics.** You and the friend must be KakaoTalk friends, and the friend must
   not have a private profile.
4. **You: get the invite link.** In Home Assistant go to *Developer tools > Actions* and run
   **`kakao_talk.friend_invite_link`** (administrators only). A notification shows the link;
   it is also in the action's response. Send it to the friend, for example in KakaoTalk.
   It is the same link for every friend and does not expire.
5. **Friend: open the link and agree.** They open the link, sign in to Kakao and tap agree on
   the consent screen (friends list and messages). What they see next depends on your
   **Friend invite landing page** setting (see [Friends away from home](#friends-away-from-home-optional)):
   * **The hosted page (recommended):** a page titled *One more step* shows them a **code**.
     They send it to you, for example in KakaoTalk.
   * **No landing page, or your own Home Assistant address:** their browser returns to Home
     Assistant, which links them automatically, and they see *Thank you*. (Away from home,
     and in Chrome, your local address does not open: use the hosted page.)
6. **You: link them (hosted page only).** Run **`kakao_talk.link_friend`** and paste their
   code (or the whole address they were sent to). Kakao links a friend to your app only when
   that code is exchanged for a token, which needs your Client secret, so a static page
   cannot do it. Home Assistant exchanges the code and throws the token away: it is never
   stored and cannot log anyone in. Do this soon after: a code works once and only for a
   short time. A notification confirms it and lists what the friend agreed to.
7. **You: check that they appear.** Kakao caches the friends list for about 10 minutes, so
   wait that long, then run `kakao_talk.list_friends`. The friend's nickname should be in
   the list. If it is not, one of the steps above is not complete for that person (see
   [Troubleshooting](#troubleshooting)).
8. **You: choose who receives messages.** The friend now appears as an entity named after
   them, for example **KakaoTalk Alice** (after the login, after `kakao_talk.list_friends`, or within an
   hour). Pick friends by name under **Targets** in the `kakao_talk.send_message` form, see
   [Picking friends by name](#picking-friends-by-name). Or add them under **Friends to send
   to** in **Configure** (without any, **every** friend Kakao returns receives every message,
   so think about what your notifications contain), or type their names per message.
9. **Try it.** For example, a message to that friend only:

   ```yaml
   action: kakao_talk.send_message
   data:
     message: Hello from Home Assistant
     friends: ["Alice"]
     send_to_me: false
   ```

Do **not** give friends a `kakao_talk.login` link: the integration stores a single account, so
their login would replace yours. The invite link cannot do that: it links the friend but never
logs anyone in. (The older way of getting a friend's permission still works: in the console's
**Tools > REST API test**, choose *Retrieve user information*, get a token with the `friends`
and `talk_message` scopes, log in as the friend and accept.)

### Friends away from home (optional)

Kakao links a friend to your app only when their one-time code is exchanged for a token, and
that needs your Client secret, so the code has to reach Home Assistant. By default Kakao sends
the friend back to your local Home Assistant address. That address only exists on your home
network, and browsers such as Chrome refuse to open it from Kakao's website (the error is
`ERR_LOCAL_NETWORK_PERMISSION_MISSING`), so the friend never reaches Home Assistant and is not
linked. There are two ways to get the code to Home Assistant:

**Recommended: the hosted page (you relay the code).** The project hosts a small themed page
on GitHub Pages, so **nothing on your Home Assistant has to be reachable from the internet**:

1. Under **Configure**, set **Friend invite landing page** to
   `https://kanemari.github.io/kakao_talk_notifier/invite-done.html`
2. In the Kakao console, register that exact address as an extra **Redirect URI** (under
   *App > Platform Key > REST API key > Redirect URI*). Keep your existing local one.
3. Run `kakao_talk.friend_invite_link` again for a fresh link.

After they agree, the friend sees *One more step* with their code and a **Copy code** button,
and sends the code to you. You run `kakao_talk.link_friend` with it (step 6 above). If they
decline they see *Permissions not accepted* instead. The page is static: it loads no other
files, stores nothing and sends nothing. Its one script shows the code as plain text (only
if it is plain URL-safe text), offers the Copy button, and removes the code from the address
bar. With a hosted page set, Home Assistant answers **nothing** from the internet.

**Alternative: your own public address (automatic).** Set **Friend invite landing page** to a
bare `https://` address of your own Home Assistant (no path, for example your Nabu Casa
address), register that address plus `/api/kakao_talk` as an extra Redirect URI, and make
sure `/api/kakao_talk` is reachable from the internet (behind a reverse proxy, allow only
that exact path and only GET requests, and set `use_x_forwarded_for` and `trusted_proxies`
under `http:`). The friend then returns to Home Assistant, which links them itself and shows
*Thank you*; nothing to relay. From the internet the integration answers only that, with fixed
text, and sends at most 6 codes a minute to Kakao. See [Security](#security).

Things to know:

* Kakao returns a friend only if they are linked to your app **and** agreed to the "Provide friends
  list in Kakao Service" permission when they linked. It leaves out anyone who set *Show my profile
  on Friends list* to *Disagree* or revoked that consent. A friend who agreed only to the message
  permission is not returned.
* Kakao caches the friends list for about 10 minutes, so a change can take that long to show.
* Before approval, an app can send 30 messages per day in total. The integration logs
  delivery failures, including the daily limit.
* Kakao accepts at most 5 recipients per request. The integration splits larger lists
  automatically.
* You also receive your own copy of each message, unless you set `send_to_me: false`.
* The friends list is refreshed once an hour. Run `kakao_talk.list_friends` to refresh
  it straight away.

## Security

The address `/api/kakao_talk` has to work without a Home Assistant login, because Kakao
sends a browser back to it. This section says what that address can and cannot do.

### What the address does

| Request | From your home network | From the internet |
|---|---|---|
| Setup page (no parameters) | Shown. It contains no keys, tokens or settings. | Refused (403) |
| Return from **your own login** (`code` + the single-use `state`) | Completes the login | Refused (403). The login stays usable at home. |
| Return with a wrong, used or expired `state` | Refused (400) | Refused (403) |
| Return from a **friend invite** | The code is exchanged with Kakao to link the friend, then a fixed thank-you text | Refused (403), unless the landing page is a bare address of your own Home Assistant: then the same |
| Anything other than a GET request | Refused (405) | Refused (405) |

It never sends a message, never shows your API key, client secret, tokens, friends or
settings, and never redirects to an address taken from the request.

### How the login is protected

Whoever completes a Kakao login becomes the account that messages are sent as, so an
outsider who could log in would receive your notifications. Three things prevent that:

* **Only a Home Assistant administrator can start a login.** `kakao_talk.login` creates a
  random single-use code (256 bits) that expires after 10 minutes. A return from Kakao
  without it is refused, and it cannot be guessed. This is the main protection, and it
  does not depend on your network or proxy.
* **A login can only be completed from your home network.** Requests from the internet,
  including Nabu Casa remote access, are refused even with a valid code. This is an extra
  layer: behind a reverse proxy that hides the visitor's address, every request looks
  local to Home Assistant, and only the single-use code protects you.
* **Every completed login creates a notification** ("KakaoTalk login completed"), so an
  unexpected one is noticed.

### Friend invites

* Kakao links a friend to your app only when their one-time code is exchanged for a token.
  When a friend returns to Home Assistant, or you run `kakao_talk.link_friend`, the
  integration exchanges the code (with your Client secret) and **throws the token away**: it
  is never stored, logged or used, so it cannot start, replace or complete a login.
* Only text that looks like a code (URL-safe characters, 10 to 512 long) is ever sent to
  Kakao, and at most 6 a minute, so a stranger cannot use the page to flood Kakao. The answer is
  always fixed text: never Kakao's words, and never the code, which is also masked out of
  anything logged.
* The hosted page cannot link anyone itself. It shows the code as plain text and the friend
  sends it to you. A code is safe to relay: it works once, briefly, and only together with
  your Client secret.
* Friend invites **require a Client secret**, and the landing page must be `https://`.
* Unless the landing page is a bare address of your own Home Assistant, nothing at all is
  answered from the internet.

### Risks that remain

* **The login link is visible to everyone who can sign in to your Home Assistant**, because
  it is shown in a notification. Someone who can sign in and is on your home network could
  open it within 10 minutes and log in with their own Kakao account; your notifications
  would then go to them until you log in again. You would see the "KakaoTalk login
  completed" notification. Dismiss the login notification if you do not use the link, and
  only give Home Assistant accounts to people you trust.
* **Friends' names and Kakao IDs are visible to every Home Assistant user** as entities, once
  friend sending is on.
* **A friend's code passes through your chat** when they send it to you. It works once and
  only briefly, and is useless without your Client secret, but it is a credential for
  linking that friend: do not forward it.
* **Anyone who can sign in to your Home Assistant can send messages** and list the friends
  with these actions, including users who are not administrators.
* **Secrets are stored unencrypted on disk**, as is usual in Home Assistant: the Kakao login
  in `kakao.session` (readable only by Home Assistant) and the API key and Client secret in
  Home Assistant's settings storage. They are included in backups, so treat backups as
  sensitive. An administrator can read the Client secret on the **Configure** form.
* **Your REST API key is part of the invite and login links.** That is how Kakao logins
  work; it is not a secret, and it is the Client secret that protects your app. Keep
  Client secret turned on.
* **A local login address that starts with `http://` is not encrypted**, so the one-time
  code crosses your home network in the clear. It is used immediately and only once, and it
  is useless without the Client secret.

### Recommendations

* Keep **Client secret** turned on in the Kakao console.
* Use a local address as `redirect_uri` and open the login link from your home network.
  Kakao redirects your own browser, so a local address works.
* Behind a reverse proxy, set `use_x_forwarded_for` and `trusted_proxies` under `http:` in
  `configuration.yaml`, so that Home Assistant sees the real address of each visitor.
  (Home Assistant rejects proxied requests when these are missing or wrong, rather than
  treating them as local.)
* Block `/api/kakao_talk` at the proxy if you do not use friend invites away from home. If
  you do, allow only that exact path and only GET requests.

## Troubleshooting

Search the Home Assistant log for `kakao_talk`. The integration logs the response Kakao
gave when something fails. To try each feature step by step, follow the
[Developer tools test guide](docs/developer-tools-test.md).

| Symptom | Likely cause |
|---|---|
| "Could not sign in to KakaoTalk" when sending or listing friends | There is no login yet, or Kakao refused the saved one. Run `kakao_talk.login`; the log has Kakao's reply. |
| Kakao shows a redirect URI error when logging in | The Redirect URI registered at Kakao does not exactly match `redirect_uri` plus `/api/kakao_talk`. |
| "This login was not started from Home Assistant, or it expired" | The login link was already used, is older than 10 minutes, or Home Assistant restarted since it was created. Run `kakao_talk.login` again. |
| The login fails with a client secret error | Set `client_secret`, or check that it is current. |
| Messages arrive but with no notification | Expected for messages to yourself. |
| No friends in the **Targets** list of `kakao_talk.send_message` | **Also send to friends** must be on, you must be logged in with the friends permission, and Kakao must return them: run `kakao_talk.list_friends`. They then appear within seconds (otherwise within an hour). |
| `kakao_talk.list_friends` shows an error such as "Kakao error -402" | Kakao refused the request; the message says why. Usually your login lacks the friends permission: turn on **Also send to friends**, run `kakao_talk.login` and agree to it. |
| `kakao_talk.list_friends` returns an empty list with a note | Kakao answered but returned nobody. Each friend must be linked to your app and have agreed to the friends-list permission (see [Sending to friends](#sending-to-friends)). Check the "KakaoTalk login completed" notification of your last login: if it does not list *friends* among the granted permissions, run `kakao_talk.login` again. If it lists a login you did not do, the integration may be logged in as someone else. |
| Tapping a message opens Home Assistant | That is the default link. Set **Button link address** to a harmless page on a registered domain, see [Avoiding Home Assistant on tap](#avoiding-home-assistant-on-tap). Turn on [debug logging](#debug-logging) and check the `link=` in the log. |
| Tapping an image does not open the image | *Open the image when tapped* is off, or the image's domain is not registered at Kakao (register `https://k.kakaocdn.net` for picked images). The log says "Sending it again with the normal link" when Kakao refused the link. |
| "The selected image comes from ... which cannot be uploaded" | Only files in **Local media** (*Media > My media*) can be uploaded. Copy the image there, or use the **Image URL** field. |
| The **Image** field in the Actions form is greyed out | Needs Home Assistant 2025.7 or newer. |
| `kakao_talk.friend_invite_link` says it needs a Client secret | Turn on Client secret for the REST API key in the Kakao console, enter it under **Configure**, and run `kakao_talk.login` again. |
| A "KakaoTalk login completed" notification you did not expect | Someone completed a Kakao login. Run `kakao_talk.login` again with your own account and review who can sign in to Home Assistant. See [Security](#security). |
| A friend agreed but does not appear in `kakao_talk.list_friends` | Kakao links a friend only when their code is exchanged. With the hosted landing page, did they send you the code and did you run `kakao_talk.link_friend` with it? Otherwise Home Assistant exchanges it when they return to it. Then wait about 10 minutes for Kakao's cache. The "KakaoTalk friend linked" notification lists what they agreed to: if it lacks *friends*, ask them to open the link again. |
| `kakao_talk.link_friend` says Kakao refused the code | A code works once and only for a short time, and only with an invite link made under the current **Friend invite landing page** setting. Ask the friend for a new link. |
| A friend says the page cannot be loaded after accepting the invite | No **Friend invite landing page** is set: Kakao sends them to your local address, which they cannot open, so they never reach Home Assistant and are not linked. Set the hosted page. |

### Debug logging

Go to **Settings > Devices & services > KakaoTalk Notifier**, open the **⋮** menu and choose
**Enable debug logging**. Send a message, then choose **Disable debug logging** to download the
log (or read it under **Settings > System > Logs > Show raw logs**). Alternatively add this to
`configuration.yaml` and restart:

```yaml
logger:
  logs:
    custom_components.kakao_talk: debug
```

Each message is logged as `Kakao send to me: type=feed link=... button='View'` (or
`send to friends`), showing exactly which link Kakao was given. A message that was sent again
after Kakao refused its link has a second line ending `(retry)`.

[hass]: https://home-assistant.io
