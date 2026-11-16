<p align="center">
  <img src="docs/icon.svg" width="96" alt="KakaoTalk Notifier icon">
</p>

<h1 align="center">KakaoTalk Notifier</h1>

A [Home Assistant][hass] custom integration that sends notifications to KakaoTalk:
to your own "My Chatroom", and optionally to Kakao Talk friends.

Unofficial project, not affiliated with or endorsed by Kakao Corp. KakaoTalk and Kakao are
trademarks of their owners.

Good to know before you start:

* Messages to yourself arrive in "My Chatroom" **silently**: no push notification and no
  unread badge. This is how Kakao delivers them.
* Kakao does not allow an app to post into group chats. Messages to other people are
  sent one-to-one (see [Sending to friends](#sending-to-friends)).

## Installation

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
5. **App > Product Link > Web domain**: register the domain that the button in your
   messages should open (see *Button link address* below). Message sending can fail if the link
   domain is not registered.

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
| Button link address (`link_url`) | no | The address the button in a message opens. Defaults to the Home Assistant address. Its domain must be registered under *App > Product Link > Web domain*. |
| Button label (`button_title`) | no | The label of the button in a message. Defaults to `View`. |
| Also send to friends (`send_to_friends`) | no | Also sends every message to Kakao Talk friends. Off by default. See [Sending to friends](#sending-to-friends). |
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
shows which permissions Kakao granted (search the log for "granted scopes").

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
JPEG or PNG, up to 5 MB.

```yaml
actions:
  - action: kakao_talk.send_message
    data:
      message: Someone is at the door.
      image:
        media_content_id: media-source://media_source/local/doorbell.jpg
        media_content_type: image/jpeg
```

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
| `notify.kakao_talk` | Sends a notification (see the examples above). |
| `kakao_talk.send_message` | The same, called directly, with the fields `message` (required), `title`, `url`, `image`, `friends`, `send_to_friends` and `send_to_me`. |
| `kakao_talk.login` | Starts a Kakao login. Administrators only. |
| `kakao_talk.list_friends` | Returns the nicknames and uuids of the friends Kakao makes available to your app. |

## Sending to friends

Kakao only lets an app message friends one-to-one, and its Message API is meant for
messages a user sends themselves, not automated ones. Until Kakao approves the
"Kakao Talk friend list / message" additional feature for a business app, you can still
use it with a small group of testers:

1. In the Kakao Developers console, under **Kakao Login > Consent items > Personal
   information**, set **Friends list in Kakao services** to *Consent during use*.
2. Under **App > Member**, invite the sender's and every recipient's Kakao account, by
   the email they log in to Kakao with. Each recipient then signs in to the Kakao
   Developers site with that account, creating a developer account if they have none.
   Your app should then appear in their app list. Kakao may also send an invitation
   message, but you do not need to wait for it.
3. The sender and each recipient must be Kakao Talk friends, and recipients must not
   have a private profile.
4. Each **recipient** links to your app once: in the console's **Tools > REST API test**,
   choose *Retrieve user information*, get a token with the `friends` and `talk_message`
   scopes, log in as the recipient and accept. Do **not** give recipients a
   `kakao_talk.login` link: the integration stores a single account, so their login would
   replace yours.
5. Turn on **Also send to friends** under **Configure** on the integration, then run `kakao_talk.login` and
   log in as the sender again, so that Kakao asks for the friends permission.
6. Run `kakao_talk.list_friends` to see who Kakao returns. An empty list means one of
   the steps above is not complete for that person.
7. Set the `friends:` list to choose the recipients. Without it, **every** friend Kakao
   returns receives every message, so think about what your notifications contain.

Things to know:

* Before approval, an app can send 30 messages per day in total. The integration logs
  delivery failures, including the daily limit.
* Kakao accepts at most 5 recipients per request. The integration splits larger lists
  automatically.
* You always receive your own copy of each message as well.
* The friends list is refreshed once an hour. Run `kakao_talk.list_friends` to refresh
  it straight away.

## Security

Whoever completes a Kakao login for this integration becomes the account that messages
are sent as, so an outsider who could log in would receive your notifications. The
address `/api/kakao_talk` has to work without a Home Assistant login, because Kakao
sends your browser back to it. The integration protects the login in two ways:

* **Only a Home Assistant administrator can start a login.** The `kakao_talk.login`
  action creates a random, single-use code that expires after 10 minutes, and a login
  that does not carry it is refused. The setup page cannot start a login and does not
  reveal your API key.
* **Requests from the internet are refused**, including Nabu Casa remote access. This is
  an extra layer, not the main protection: behind a reverse proxy that hides the
  visitor's address, every request looks local to Home Assistant.

Recommendations:

* Use a local address as `redirect_uri` and open the login link from your home network.
  Kakao redirects your own browser, so a local address works.
* If Home Assistant is reachable through a reverse proxy, block the path
  `/api/kakao_talk` at the proxy. Also set `use_x_forwarded_for` and `trusted_proxies`
  under `http:` in `configuration.yaml`, so that Home Assistant sees the real address of
  each visitor.
* The login notification is visible to everyone who can sign in to your Home Assistant.
  Dismiss it if you do not use the link.
* Anyone who can sign in to your Home Assistant can send messages with these actions.
* The Kakao login is stored in the file `kakao.session` in your configuration folder.
  It is included in backups, so treat those as sensitive.

## Troubleshooting

Search the Home Assistant log for `kakao_talk`. The integration logs the response Kakao
gave when something fails.

| Symptom | Likely cause |
|---|---|
| "Not logged in to KakaoTalk" | Run `kakao_talk.login`. |
| Kakao shows a redirect URI error when logging in | The Redirect URI registered at Kakao does not exactly match `redirect_uri` plus `/api/kakao_talk`. |
| "This login was not started from Home Assistant, or it expired" | The login link was already used, is older than 10 minutes, or Home Assistant restarted since it was created. Run `kakao_talk.login` again. |
| The login fails with a client secret error | Set `client_secret`, or check that it is current. |
| Messages arrive but with no notification | Expected for messages to yourself. |
| `kakao_talk.list_friends` returns nothing | See the steps in [Sending to friends](#sending-to-friends). |

[hass]: https://home-assistant.io
