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
    https://github.com/clipman/kakao_talk
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

Login KakaoTalk service by clicking '카카오톡 로그인' button.<br>

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
