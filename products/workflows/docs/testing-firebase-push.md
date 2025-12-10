# Testing Firebase Push Notifications

This guide covers how to test the Firebase Push Notification destination locally.

## Quick Test (Standalone Script)

The fastest way to validate your Firebase setup is using the standalone test script:

```bash
cd ~/dev/posthog/products/workflows/docs
python test_fcm_push.py <path-to-service-account.json> <fcm-token>
```

This script bypasses PostHog entirely and calls FCM directly, helping isolate Firebase setup issues.

## Test Credentials

**Firebase service account**: [1Password](https://start.1password.com/open/i?a=VYI5XOSPGVCMNAOIJ2AKYWOXUA&v=o2cmwvhcovs3sn3zrvpunfkq74&i=ojhte5e6nf7pmh4vs2b7aaba3u&h=posthog.1password.com)

Project ID: `posthog-7d74b`

## Getting an FCM Token

### Option 1: Android Emulator (Recommended)

Android emulators support FCM (iOS simulators don't).

**Prerequisites:**

- Android Studio ([download](https://developer.android.com/studio))
- Java 17+

**Step 1: Clone Firebase quickstart**

```bash
cd ~/dev
git clone https://github.com/firebase/quickstart-android.git
cd quickstart-android/messaging
```

**Step 2: Add Android app to Firebase**

1. Go to [Firebase Console](https://console.firebase.google.com/) → your project
2. Click "Add app" → Android
3. Package name: `com.google.firebase.quickstart.fcm`
4. Download `google-services.json`
5. Copy to `quickstart-android/messaging/app/google-services.json`

**Step 3: Create emulator with Google Play Services**

1. Android Studio → Tools → Device Manager
2. Create Device → Select Pixel 6 (or similar)
3. **IMPORTANT**: Select system image with "Google Play" or "Google APIs"
   - Recommended: API 34 (Android 14) with Google Play
4. Start the emulator

**Step 4: Run the app**

```bash
cd ~/dev/quickstart-android/messaging
./gradlew installDebug
```

Or open in Android Studio and click Run.

**Step 5: Get the token**

1. Open Logcat (View → Tool Windows → Logcat)
2. Filter by "FCM" or "RegistrationToken"
3. Look for: `D/MainActivity: FCM Registration Token: <your-token>`
4. Copy this token!

### Option 2: Physical iOS Device

iOS simulators don't support push. You need a real iPhone.

```swift
import FirebaseMessaging

// In AppDelegate after Firebase.configure()
Messaging.messaging().token { token, error in
    if let token = token {
        print("FCM Token: \(token)")  // Copy this!
    }
}
```

### Option 3: Custom Android App

```kotlin
FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
    if (task.isSuccessful) {
        Log.d("FCM", "Token: ${task.result}")  // Copy this!
    }
}
```

## Testing via Django Shell

Create a Firebase integration directly:

```bash
cd ~/dev/posthog
flox activate -- python manage.py shell
```

```python
from posthog.models import Team, User
from posthog.models.integration import Integration, FirebaseIntegration

# Check existing integrations
Integration.objects.filter(kind='firebase').first()

# Or create one (see integration_from_key for full setup)
```

## Loading the Template

The Firebase Push Notification template lives in the plugin-server and needs to be synced to the database.

**Option 1: Automatic sync (requires plugin-server running)**

```bash
flox activate -- python manage.py sync_hog_function_templates
```

This fetches templates from the plugin-server at `localhost:6738`. If the plugin-server keeps crashing (common MinIO/blobby issue), use Option 2.

**Option 2: Manual database insert**

If the plugin-server is unstable, you can insert the template directly:

```bash
flox activate -- python manage.py shell
```

```python
from posthog.models.hog_function_template import HogFunctionTemplate

# Check if it already exists
if HogFunctionTemplate.objects.filter(template_id='template-firebase-push').exists():
    print("Template already exists!")
else:
    code = '''
let fcmToken := inputs.fcm_token
let title := inputs.title
let body := inputs.body
let projectId := inputs.firebase_account.project_id

if (not fcmToken) {
    throw Error('FCM token is required')
}

if (not title) {
    throw Error('Notification title is required')
}

let url := f'https://fcm.googleapis.com/v1/projects/{projectId}/messages:send'

let message := {
    'message': {
        'token': fcmToken,
        'notification': {
            'title': title,
            'body': body
        }
    }
}

if (inputs.data) {
    message.message.data := inputs.data
}

let payload := {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.firebase_account.access_token}',
        'Content-Type': 'application/json'
    },
    'body': message
}

if (inputs.debug) {
    print('Sending push notification', url, payload)
}

let res := fetch(url, payload)

if (res.status < 200 or res.status >= 300) {
    throw Error(f'Failed to send push notification via FCM: {res.status} {res.body}')
}

if (inputs.debug) {
    print('Push notification sent', res)
}
'''

    template = HogFunctionTemplate.objects.create(
        template_id='template-firebase-push',
        name='Firebase Push Notification',
        description='Send push notifications to mobile devices via Firebase Cloud Messaging (FCM)',
        type='destination',
        status='alpha',
        free=False,
        icon_url='/static/services/firebase.png',
        category=['Communication'],
        code_language='hog',
        code=code,
        inputs_schema=[
            {'key': 'firebase_account', 'type': 'integration', 'integration': 'firebase', 'label': 'Firebase project', 'requiredScopes': 'placeholder', 'secret': False, 'hidden': False, 'required': True},
            {'key': 'fcm_token', 'type': 'string', 'label': 'FCM device token', 'secret': False, 'required': True, 'description': 'The Firebase Cloud Messaging token for the target device.', 'default': '', 'templating': 'liquid'},
            {'key': 'title', 'type': 'string', 'label': 'Notification title', 'secret': False, 'required': True, 'description': 'The title of the push notification', 'default': 'Notification from {{ event.event }}', 'templating': 'liquid'},
            {'key': 'body', 'type': 'string', 'label': 'Notification body', 'secret': False, 'required': False, 'description': 'The body text of the push notification', 'default': '', 'templating': 'liquid'},
            {'key': 'data', 'type': 'json', 'label': 'Custom data payload', 'secret': False, 'required': False, 'description': 'Optional custom key-value data to send with the notification', 'default': {}},
            {'key': 'debug', 'type': 'boolean', 'label': 'Log responses', 'description': 'Logs the FCM responses for debugging.', 'secret': False, 'required': False, 'default': False},
        ],
    )
    print(f"Created template: {template.template_id}")
```

After loading, refresh the destinations page and you should see "Firebase Push Notification".

## Testing via PostHog UI

1. Start PostHog locally
2. Go to Data pipelines → Destinations → "Firebase Push Notification"
3. Click "Choose Firebase connection" → "Upload Firebase service account .json key file"
4. Upload your service account JSON
5. Configure:
   - **FCM device token**: Paste token from test app
   - **Notification title**: "Test notification"
   - **Notification body**: "Hello from PostHog!"
   - **Debug**: Enable for logging
6. Set up a filter (e.g., event name = `test_push`)
7. Trigger an event matching your filter
8. Check your test device!

## Foreground vs Background

**Important**: When your app is in the **foreground**, FCM delivers messages to your app's message handler instead of showing a system notification. You'll see the message in Logcat:

```text
MyFirebaseMsgService  D  From: 725655360102
MyFirebaseMsgService  D  Message Notification Body: If you see this, FCM is working! 🎉
```

To see an actual notification popup, **background the app** (press Home) before sending the push.

## Triggering Test Events

Use the capture endpoint on port 8010 (not 8000):

```bash
curl -X POST http://localhost:8010/e/ \
  -H "Content-Type: application/json" \
  -d '{
    "api_key": "<your-project-api-key>",
    "event": "test_push",
    "distinct_id": "test-user-123",
    "properties": {}
  }'
```

To find your project API key:

```bash
flox activate -- python manage.py shell -c "from posthog.models import Team; print(Team.objects.first().api_token)"
```

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| 401 Unauthorized | Invalid service account or missing permissions | Re-download service account JSON, ensure Cloud Messaging API is enabled |
| 404 Not Found | Project ID mismatch | Check project_id in JSON matches Firebase project |
| 400 Bad Request | Invalid/expired FCM token | Get a fresh token from your app |
| No notification banner | App is in foreground | Background the app before sending push |
| No notification | App force-closed or no permissions | Check app has notification permissions, is in foreground/background |
| UNREGISTERED | Token no longer valid | App was uninstalled or token rotated - get new token |
| "Can't use cohorts in real-time filters" | Filter checkbox uses cohorts | Uncheck "Filter out internal and test users" when saving destination |
| Firebase logo not showing | Static file not copied | Run `cp frontend/public/services/firebase.png staticfiles/services/firebase.png` |
| FCM returns error | FCM token has line breaks | Ensure token is pasted as single line with no whitespace/newlines |
| 403 CSRF error on /capture/ | Wrong endpoint | Use `http://localhost:8010/e/` not `http://localhost:8000/capture/` |

## Running Unit Tests

```bash
# Integration model tests
cd ~/dev/posthog
flox activate -- pytest posthog/models/test/test_integration_model.py::TestFirebaseIntegrationModel -v

# Hog template tests (if they exist)
cd ~/dev/posthog/plugin-server
pnpm test src/cdp/templates/_destinations/firebase_push/
```
