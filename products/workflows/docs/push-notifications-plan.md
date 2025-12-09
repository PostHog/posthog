# Push Notifications for Workflows

## Overview

Enable PostHog workflows to send push notifications to customers' mobile app users via Firebase Cloud Messaging (FCM).

## Architecture

PostHog acts as a conduit - customers provide their Firebase credentials, we send pushes on their behalf. The push appears to come from the customer's app.

| What | Answer |
|------|--------|
| Whose app? | The PostHog customer's app |
| Whose Firebase credentials? | The customer's (stored in Integration) |
| Whose device tokens? | The customer's end users |
| Who sees the notification? | The customer's end users |
| What app name appears? | The customer's app name |

## Vertical Slices

### Slice 1: Backend can send a push (hardcoded token)

- Integration model: Add `FIREBASE` to `IntegrationKind`
- Integration UI: Upload service account JSON
- Hog template: Inputs for title, body, FCM token field
- Push service: POST to FCM API with JWT auth
- Test with a manually-provided FCM token

### Slice 2: iOS SDK captures and sends FCM token

- Add `setFcmToken(token:)` method to posthog-ios
- Store token in SDK storage
- Send token to backend (stored in `PushSubscription` model, NOT as person property)
- Handle token refresh (Firebase can rotate tokens)

### Slice 3: Workflow looks up token from PushSubscription

- Template reads token from `PushSubscription` table by distinct_id
- End-to-end: event -> workflow -> push

### Slice 4: Android SDK (same pattern)

- `setFcmToken()` for posthog-android

### Slice 5: Rich push (Notification Service Extension)

- Image attachments, action buttons, deep links

## Components

### Backend

| Component | Location | Purpose |
|-----------|----------|---------|
| Integration type | `posthog/models/integration.py` | Add `FIREBASE` to `IntegrationKind` |
| PushSubscription model | `posthog/models/push_subscription.py` | Store tokens securely (NOT as person properties) |
| Hog function template | `plugin-server/src/cdp/templates/_destinations/firebase/` | Defines push action UI + Hog code |
| Push service | `plugin-server/src/cdp/services/messaging/push.service.ts` | Calls FCM API |

### Frontend

| Component | Purpose |
|-----------|---------|
| Integration setup UI | Collect Firebase service account JSON |
| Workflow action node | "Send push notification" in workflow editor |
| Action config form | Title, body, data payload fields |

### SDK (iOS)

Follow Braze's approach - offer both manual and automatic modes. Start with manual.

**Manual mode** (customer implements):

```swift
// In AppDelegate
func application(_ application: UIApplication,
                 didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
    PostHogSDK.shared.registerPushToken(deviceToken)
}

// Firebase token refresh
func messaging(_ messaging: Messaging, didReceiveRegistrationToken fcmToken: String?) {
    if let token = fcmToken {
        PostHogSDK.shared.setFcmToken(token)
    }
}
```

**Automatic mode** (future - SDK handles via swizzling like OneSignal).

## Token Storage

**Security concern**: Person properties are readable via API. FCM tokens should NOT be stored there.

**Solution**: New `PushSubscription` model:

```python
# posthog/models/push_subscription.py

class PushPlatform(models.TextChoices):
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"

class PushSubscription(UUIDTModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Link to person
    distinct_id = models.CharField(max_length=512)

    # The actual token (consider encryption)
    token = models.TextField()

    # Platform info
    platform = models.CharField(max_length=16, choices=PushPlatform.choices)

    # Track if token is still valid
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("team", "distinct_id", "token")
```

Follows pattern from `MessageRecipientPreference` in `posthog/models/message_preferences.py`.

## Reference Implementations

### Existing PostHog patterns

- Email template: `plugin-server/src/cdp/templates/_destinations/email/email.template.ts`
- Email service: `plugin-server/src/cdp/services/messaging/email.service.ts`
- SMS/Twilio: `plugin-server/src/cdp/templates/_destinations/twilio/twilio.template.ts`
- Message preferences: `posthog/models/message_preferences.py`

### External SDKs

- [OneSignal iOS SDK](https://github.com/OneSignal/OneSignal-iOS-SDK) - Fully automatic (swizzling)
- [Braze Swift SDK](https://github.com/braze-inc/braze-swift-sdk) - Offers both automatic and manual modes
- [Laudspeaker Swift SDK](https://github.com/laudspeaker/laudspeaker-swift-sdk) - Manual only

## SDK Comparison

| SDK | Approach | Developer Work |
|-----|----------|----------------|
| OneSignal | Always automatic (swizzling) | Just `initialize()` + `requestPermission()` |
| Braze | Choice of automatic or manual | Auto: 1 line. Manual: ~70 lines |
| Laudspeaker | Manual only | Call `setFcmToken()` in AppDelegate |

**Recommendation**: Start with manual (like Laudspeaker/Braze manual), add automatic later.

## Documentation Needed

Customer setup guide:

1. Set up Firebase project
2. Add PostHog SDK to app
3. Wire up token callbacks to PostHog SDK
4. Upload Firebase credentials to PostHog
5. Create workflow with push action

```swift
// Example for docs
func messaging(_ messaging: Messaging, didReceiveRegistrationToken fcmToken: String?) {
    PostHogSDK.shared.setFcmToken(fcmToken)
}
```

## Testing Slice 1

### Firebase Setup

1. Go to [Firebase Console](https://console.firebase.google.com/)
2. Create a new project (or use existing)
3. Go to Project Settings → Cloud Messaging and ensure it's enabled
4. Go to Project Settings → Service accounts → "Generate new private key"
5. Save the JSON file - this is what you'll upload to PostHog

### Get an FCM Token (Test App)

You need a simple iOS/Android app to get a device token:

**iOS (simplest approach)**:

```swift
import FirebaseMessaging

// In AppDelegate after Firebase.configure()
Messaging.messaging().token { token, error in
    if let token = token {
        print("FCM Token: \(token)")  // Copy this!
    }
}
```

**Android**:

```kotlin
FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
    if (task.isSuccessful) {
        Log.d("FCM", "Token: ${task.result}")  // Copy this!
    }
}
```

### Test in PostHog

1. Start PostHog locally
2. Go to Data pipelines → Destinations → "Firebase Push Notification"
3. Click "Choose Firebase connection" → "Upload Firebase service account .json key file"
4. Upload your service account JSON
5. Configure the destination:
   - **FCM device token**: Paste the token from your test app
   - **Notification title**: "Test notification"
   - **Notification body**: "Hello from PostHog!"
   - **Debug**: Enable for logging
6. Set up a filter (e.g., event name = "test_push")
7. Trigger an event matching your filter
8. Check your test device - you should receive the push notification!

### Troubleshooting

- **401 Unauthorized**: Service account JSON is invalid or doesn't have Cloud Messaging permissions
- **404 Not Found**: Project ID in the service account doesn't match a valid Firebase project
- **400 Bad Request**: Usually means the FCM token is invalid or expired (get a new one from your app)
- **No notification received**: Check that your app has notification permissions and is in the foreground/background (not force-closed)

## Open Questions

- Do we need delivery tracking? (Firebase provides some via their console)
- Rich push in slice 5 - how much to support initially?
- Web push - same system or separate?
