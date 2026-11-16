# Testing KakaoTalk from Developer Tools

Developer Tools has two tabs that matter here, and they do different jobs:

* **Template** only renders text. It cannot call actions, so it builds and checks the
  payload.
* **Actions** (YAML mode) calls the action and shows any response.

## 1. Template tab: build and validate the payload

Paste this into **Developer Tools → Template**. Edit the first block, and read the output.

```jinja
{# ---- edit these ---- #}
{% set title   = "Front door" %}
{% set message = "Someone is at the door at " ~ now().strftime('%H:%M') %}
{% set photos  = ["https://example.com/doorbell.jpg"] %}
{# -------------------- #}

{%- set body = (title ~ "\n\n" ~ message) if title else message %}
Text sent to Kakao ({{ body | length }} chars; Kakao text templates are limited to roughly 200):
────────────
{{ body }}
────────────

{% if photos | length == 0 -%}
Type: plain text message (1 message)
{%- else -%}
Type: image card, one message per image ({{ photos | length }} message{{ 's' if photos | length > 1 }})
{%- endif %}
{% for p in photos %}
{{ loop.index }}. {{ p }}
   {{ '✅ https URL' if p.startswith('https://') else ('⚠️ http only, may be blocked' if p.startswith('http://') else '❌ not a URL') }}
   {{ '✅ looks like an image' if p.split('?')[0].lower().endswith(('.png','.jpg','.jpeg','.gif','.webp')) else '⚠️ no image extension, check it opens as an image' }}
{% endfor %}

notify.kakao_talk payload:
{{ {"title": title, "message": message, "data": {"photo": photos | map('urlize') | map('striptags') | list}} | to_json(pretty_print=True) }}
```

## 2. Actions tab: call each feature

Switch **Developer Tools → Actions** to **YAML mode**, paste one block, and press
**Perform action**. Test in this order.

**a) List friends** (shows nicknames and uuids in the response panel, and refreshes the cache):

```yaml
action: kakao_talk.list_friends
```

**b) Plain text:**

```yaml
action: kakao_talk.send_message
data:
  title: Test title
  message: "Plain text test {{ now().strftime('%H:%M:%S') }}"
```

**c) Image card** (the URL must be public, since Kakao and the phone load it):

```yaml
action: kakao_talk.send_message
data:
  title: Test image
  message: Image card test
  url: https://example.com/doorbell.jpg
```

**d) Through the notify service, several images** (one message per image):

```yaml
action: notify.kakao_talk
data:
  title: Notify test
  message: Multiple images
  data:
    photo:
      - https://example.com/doorbell.jpg
      - url: https://example.com/snapshot.png
```

**e) Login link** (administrators only):

```yaml
action: kakao_talk.login
```

**f) Image from your media, to one friend only** (use the media picker in UI mode, or
the `media-source://` id in YAML; replace the nickname with one from step a):

```yaml
action: kakao_talk.send_message
data:
  title: Media test
  message: Uploaded image to one friend
  image:
    media_content_id: media-source://media_source/local/test.jpg
    media_content_type: image/jpeg
  friends: ["Alice"]
  send_to_me: false
```

**g) Through notify to chosen friends:**

```yaml
action: notify.kakao_talk
data:
  message: notify to chosen friends
  data:
    friends: ["Alice"]
    send_to_me: false
```

**h) Tap opens the image (register the image's domain at Kakao first):**

```yaml
action: kakao_talk.send_message
data:
  title: Tap test
  message: Tapping this should open the image
  url: https://example.com/doorbell.jpg
  link_to_image: true
```

On your phone, tap the message and check that the image opens, not Home Assistant. If the
domain is not registered the message still arrives, tapping opens the normal link, and the
log says "Sending it again with the normal link".

**j) Friend invite link (administrators only):**

```yaml
action: kakao_talk.friend_invite_link
```

A notification shows the link (it is also in the response panel). Open it in a browser signed in
as an invited friend's Kakao account: you should get Kakao's consent screen for the friends
list and messages. After you agree, the page may say it cannot be loaded if you are not on
the home network; that is fine. Then run `kakao_talk.list_friends` as the sender to see whether
the friend now appears.

**i) Debug log of the link:** add this to `configuration.yaml` (or use *Settings > System >
Logs > Set log level*), send any message, and read the line `Kakao send to me: type=...
link=...`:

```yaml
logger:
  logs:
    custom_components.kakao_talk: debug
```

## Notes

* `friends`, `send_to_friends` and `send_to_me` are per message. The configured
  `friends:` list is only the default.
* `friends` needs *Also send to friends* turned on in the integration settings (the login must include
  the friends permission). An unknown friend name is logged, and if none match the action
  fails with an error.
* `image` uploads a local JPEG/PNG (max 5 MB) to Kakao; `url` is for images already
  public. Use one or the other.
* `link_to_image` and `link_url` also work in the `data` of `notify.kakao_talk`, and per
  photo (`photo: [{url: ..., link_url: ...}]`).
* If there is no valid Kakao login, sending and `list_friends` fail with "Could not sign
  in to KakaoTalk" instead of appearing to succeed. Run `kakao_talk.login` (step e).
* Mistakes in the call itself (both `url` and `image`, both targets off, an unknown
  friend) are reported as validation errors, not server errors.
* A template cannot call `list_friends`, so the friend list shows in the Actions response
  panel, not in the Template tab.
