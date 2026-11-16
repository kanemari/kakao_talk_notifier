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
{% set photos  = ["https://i.ibb.co/jkbTKZz/hassio.png"] %}
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
  url: https://i.ibb.co/jkbTKZz/hassio.png
```

**d) Through the notify service, several images** (one message per image):

```yaml
action: notify.kakao_talk
data:
  title: Notify test
  message: Multiple images
  data:
    photo:
      - https://i.ibb.co/jkbTKZz/hassio.png
      - url: http://k.kakaocdn.net/dn/bDgfik/btqwQWk4CRU/P6wNJJiQ3Ko21KNE1TiLw1/kakaolink40_original.png
```

**e) Login link** (administrators only):

```yaml
action: kakao_talk.login
```

## Limits of the current integration

* **Friend selection is not possible per call.** `send_message` only takes `title`,
  `message` and `url`. Recipients come from `send_to_friends` and the `friends:` list in
  `configuration.yaml`, and changing them needs a restart. To test one friend, copy their
  uuid from step (a) into `friends:`.
* **Image upload is not supported.** Images are URLs only. For a local image, serve it
  from `/config/www/` (reachable as `/local/...`) and use a public URL such as your
  Nabu Casa or reverse-proxy address.
* A template cannot call `list_friends`, so the friend list shows in the Actions response
  panel, not in the Template tab.

Per-call friend selection and image upload would need integration changes (extra
`send_message` fields such as `friends`, plus a `selector: media` image field that copies
the file to `/config/www`). Say if you want those added.
