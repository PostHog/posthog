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

## Current Status

**Slices 1, 2, and 3 are complete!**

### What's Done

**Slice 1 - Backend can send push:**

- ✅ `FIREBASE` added to `IntegrationKind` in `posthog/models/integration.py`
- ✅ `FirebaseIntegration` class with token refresh logic
- ✅ API endpoint for service account JSON upload
- ✅ Hog function template at `plugin-server/src/cdp/templates/_destinations/firebase_push/`
- ✅ Frontend: types, icons, IntegrationChoice UI
- ✅ Unit tests for `FirebaseIntegration`
- ✅ Template tests for Hog function
- ✅ Standalone FCM test script validated (push received on Android emulator)
- ✅ Firebase integration created via Django shell
- ✅ End-to-end test through PostHog workflows (event → destination → FCM push → notification on device)

**Slice 2 - Android SDK captures FCM token:**

- ✅ Added `setFcmToken(token: String)` to PostHog Android SDK
- ✅ Added `setFcmTokenStateless(distinctId, token)` for stateless usage
- ✅ Token stored in SDK preferences (key: `fcmToken`)
- ✅ API client method `registerPushSubscription()` sends to `/sdk/push_subscriptions/register/`
- ✅ Published SDK v3.27.2 to mavenLocal for testing
- ✅ PR: https://github.com/PostHog/posthog-android/pull/new/matt/fcm-token-support

**Slice 3 - Workflow looks up token:**

- ✅ Modified Firebase Push Hog function template to support token lookup
- ✅ Added `lookup_tokens` boolean input (defaults to true)
- ✅ Calls internal `/api/internal/push_subscriptions/lookup/` endpoint
- ✅ Falls back to manual `fcm_token` input if lookup disabled or no token found
- ⏳ End-to-end testing blocked: Plugin-server ingestion consumer not running locally (events reach Kafka but not ClickHouse, so Hog functions never trigger)
- ✅ PR: https://github.com/PostHog/posthog/pull/new/matt/push-token-lookup

**Known blockers:**

- Plugin-server `clickhouse-ingestion` consumer group shows 0 members - ingestion pipeline not processing events locally
- This prevents end-to-end testing of Slice 3 (auto token lookup) in local dev environment
- SDK token registration works (verified via database), manual token input works, auto-lookup code is implemented but untested end-to-end

## Vertical Slices

### Slice 1: Backend can send a push (hardcoded token) ✅ Complete

- ✅ Integration model: Add `FIREBASE` to `IntegrationKind`
- ✅ Integration UI: Upload service account JSON
- ✅ Hog template: Inputs for title, body, FCM token field
- ✅ Push service: POST to FCM API with JWT auth
- ✅ End-to-end tested with manually-provided FCM token

### Slice 2: Android SDK captures and sends FCM token ✅ Complete

- ✅ Add `setFcmToken(token)` method to posthog-android
- ✅ Store token in SDK storage
- ✅ Send token to backend (stored in `PushSubscription` model, NOT as person property)
- ⏳ Handle token refresh (Firebase can rotate tokens) - SDK supports it, needs integration testing

### Slice 3: Workflow looks up token from PushSubscription ⏳ Implementation complete, E2E blocked

- ✅ Template reads token from `PushSubscription` table by distinct_id
- ✅ Implementation complete and code-reviewed
- ⏳ End-to-end testing blocked by local dev environment issue (plugin-server ingestion not running)

### Slice 4: iOS SDK (same pattern)

- `setFcmToken(token:)` for posthog-ios

### Slice 5: Rich push (Notification Service Extension)

- Image attachments, action buttons, deep links

## Components

### Backend

| Component | Location | Purpose |
|-----------|----------|---------|
| Integration type | `posthog/models/integration.py` | Add `FIREBASE` to `IntegrationKind` |
| PushSubscription model | `posthog/models/push_subscription.py` | Store tokens securely (NOT as person properties) |
| Hog function template | `plugin-server/src/cdp/templates/_destinations/firebase_push/` | Defines push action UI + Hog code |
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

## Testing

See [testing-firebase-push.md](testing-firebase-push.md) for detailed testing instructions.

**Test credentials**: [Firebase service account in 1Password](https://start.1password.com/open/i?a=VYI5XOSPGVCMNAOIJ2AKYWOXUA&v=o2cmwvhcovs3sn3zrvpunfkq74&i=ojhte5e6nf7pmh4vs2b7aaba3u&h=posthog.1password.com)

## Open Questions

- Do we need delivery tracking? (Firebase provides some via their console)
- Rich push in slice 5 - how much to support initially?
- Web push - same system or separate?
