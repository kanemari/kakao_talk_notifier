# kakao_talk
The **kakao_talk** platform uses KakaoTalk to deliver notifications from [Home Assistant][hass] to your Android device, your Windows phone, or your iOS device.

<div>
  <img width="600" src="https://user-images.githubusercontent.com/11463289/69047831-69a72300-0a3f-11ea-9382-94141f96a88e.png"/>
</div>

## Installation

HACS
* Custom repositories
```
  Repository:
    https://github.com/kanemari/kakao_talk_notifier
  Category:
    Integration
```
* Kakao Talk Download

## Setup

The requirements are:
* You need the REST API Key for KakaoTalk.
* In the Kakao Developers console: enable **Kakao Login**, add the Redirect URI below, enable the
  **KakaoTalk Message (talk_message)** consent item, and register your Home Assistant domain under
  *Platform > Web* (message links use it). If **Client Secret** is enabled, set `client_secret`.

To enable KakaoTalk notifications in your installation, add the following to your `configuration.yaml` file:
```
kakao_talk:
  api_key: YOUR_REST_API_KEY
  client_secret: YOUR_CLIENT_SECRET   # required if Client Secret is enabled in the Kakao console
  redirect_uri: YOUR_HASSIO_URL       # include http:// or https:// and the port
  send_to_friends: False              # True also needs the 'friends' consent item
  button_title: View                  # optional; label of the button in the message
  friends:                            # optional; only send to these friends (nickname or uuid)
    - Alice
  
notify:
  - platform: kakao_talk
    name: kakao_talk
```
Example)
```
kakao_talk:
  api_key: ef15xxxxx3ac00934e4d7e0ab41xxxxx
  redirect_uri: http://xxxxx.duckdns.org:8123
  send_to_friends: True
  
notify:
  - platform: kakao_talk
    name: kakao_talk
```

Restart the Home Assistant.

And type YOUR_HASSIO_URL/api/kakao_talk on the web browser such as Chrome, Firefox...<br>
You can see below screen then you can find the Login Redirection URI, 
it should be input Login Redirection URI on the Kakao Development site.<br>
<br>
Redirect URI Example)
```
http://xxxxx.duckdns.org:8123/api/kakao_talk
```
https://developers.kakao.com/
<br><br>
![Kakao_Login_Screen](https://user-images.githubusercontent.com/11463289/69050463-73cc2000-0a45-11ea-8445-734e60556bd1.png)

Log in to the KakaoTalk service by clicking the "Log in with KakaoTalk" button.<br>

## Configuration

To use notifications, please see the [getting started with automation page][hass2].

### Text message

```yaml
...
actions:
  - action: notify.kakao_talk
    data:
      title: Send a message
      message: A simple text notification.
```

#### CONFIGURATION VARIABLES
* **title:**
>>  **description**: Will be composed as '%title\n%message'.<br>
>>  **required**: false<br>
>>  **type**: string<br>
* **message:**
>>  **description**: Message text.<br>
>>  **required**: true<br>
>>  **type**: string<br>

### Photo support

```yaml
...
actions:
  - action: notify.kakao_talk
    data:
      title: Send an image
      message: Example notification with an image.
      data:
        photo:
          - url: https://i.ibb.co/jkbTKZz/hassio.png
```

#### CONFIGURATION VARIABLES
* **url:**
>>  **description**: A remote path to an image.<br>
>>  **required**: true to support Photo<br>
>>  **type**: string<br>

![image_sample](https://user-images.githubusercontent.com/11463289/69052464-6e250900-0a4a-11ea-8c5c-844caa8d9983.png)

[hass]: https://home-assistant.io
[hass2]: https://www.home-assistant.io/getting-started/automation/

## Sending to friends

Kakao only lets an app message friends one-to-one (not group chats), and the
Message API is meant for messages a user sends themselves. Until Kakao approves
the "Kakao Talk friend list / message" additional feature for a business app,
you can still use it with a small group of testers:

1. In the Kakao Developers console, under **Kakao Login > Consent items**, set
   **Friends list in Kakao services** to *Consent during use*.
2. Under **App > Member**, invite the sender's and every recipient's Kakao account
   (by the email they log in with).
3. The sender and each recipient must be Kakao Talk friends, and recipients must not
   have a private profile.
4. Each **recipient** links to your app once: in the console's **Tools > REST API test**,
   choose *Retrieve user information*, get a token with the `friends` and `talk_message`
   scopes, log in as the recipient and accept. Do **not** have recipients log in at
   `/api/kakao_talk`; that page stores a single token, so a second login would replace yours.
5. Set `send_to_friends: True`, restart, log in as the sender at `/api/kakao_talk` again
   (this re-requests the `friends` scope), then run the `kakao_talk.list_friends` action
   (Developer tools > Actions, with "Response" shown) to see nicknames and uuids.
6. Optionally restrict recipients with the `friends:` list. Without it, every friend Kakao
   returns receives each message.

Limits before approval: 30 messages per day for the whole app, and 5 recipients per
request (the integration batches automatically). Delivery failures, including the daily
limit, are logged by the integration.
