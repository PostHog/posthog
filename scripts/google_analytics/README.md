# Google analytics import

## Authentication
In order to use the google analytics api you will need to first get authenticated

1. Visit https://console.developers.google.com/apis/credentials
2. Create a new credential - OAuth Client ID
3. The application type will be `other`
4. Download the JSON and place it on this folder.

## Preparation

1. Fill out the information on constant.py
  * `CREDENTIALS_FILE_PATH`: where you places the client_secrets
  * `END_DATE`: When the google analytics window should end
  * `START_DATE`: When the google analytics window should start
  * `VIEW_ID`: The id for the view. This can be found [following this guide](https://stackoverflow.com/a/47921777)
  * `METRICS`: What metrics you want to follow. [Full list here](https://ga-dev-tools.appspot.com/dimensions-metrics-explorer/)
  * `DIMENSIONS`: What dimensions you want to follow. [Full list here](https://ga-dev-tools.appspot.com/dimensions-metrics-explorer/)
