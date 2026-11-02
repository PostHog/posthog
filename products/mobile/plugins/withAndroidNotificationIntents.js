const { withMainActivity } = require('expo/config-plugins')

// Expo SDK 57 drops onNewIntent while expo-updates is loading the app. Hand FCM taps to its
// notification queue before that delegate can drop them: https://github.com/expo/expo/issues/49254.
const INTENT_HANDLER = `
  override fun onNewIntent(intent: android.content.Intent) {
    val extras = intent.extras
    if (extras?.containsKey("google.message_id") == true) {
      val initialId = getSharedPreferences("posthog_notification_intents", MODE_PRIVATE)
        .getString("initial_message_id", null)
      if (extras.getString("google.message_id") != initialId) {
        expo.modules.notifications.notifications.NotificationManager.onNotificationResponseFromExtras(Bundle(extras))
      }
      intent.removeExtra("google.message_id")
    }
    setIntent(intent)
    super.onNewIntent(intent)
  }
`

// Android keeps its own copy of the task's original launch intent across process death.
// Remember that one ID so a restored tap cannot occupy Expo's first-only pending-response slot.
const INITIAL_INTENT = `
    val initialMessageId = intent.getStringExtra("google.message_id")
    if (initialMessageId != null) {
      val preferences = getSharedPreferences("posthog_notification_intents", MODE_PRIVATE)
      if (preferences.getString("initial_message_id", null) == initialMessageId) {
        intent.removeExtra("google.message_id")
      } else {
        preferences.edit().putString("initial_message_id", initialMessageId).apply()
      }
    }
`

const CREATE_ANCHOR = 'super.onCreate(null)'
const CLASS_ANCHOR = 'class MainActivity : ReactActivity() {'
const MARKER = '// posthog-notification-intents'

module.exports = function withAndroidNotificationIntents(config) {
    return withMainActivity(config, (cfg) => {
        const { contents, language } = cfg.modResults
        if (contents.includes(MARKER)) {
            return cfg
        }
        if (
            language !== 'kt' ||
            !contents.includes(CLASS_ANCHOR) ||
            !contents.includes(CREATE_ANCHOR) ||
            contents.includes('override fun onNewIntent(')
        ) {
            throw new Error(
                'withAndroidNotificationIntents: MainActivity does not match the Expo SDK 57 template. Update or remove this plugin.'
            )
        }
        cfg.modResults.contents = contents
            .replace(CLASS_ANCHOR, `${CLASS_ANCHOR}\n  ${MARKER}\n${INTENT_HANDLER}`)
            .replace(
                CREATE_ANCHOR,
                `${INITIAL_INTENT}\n    ${CREATE_ANCHOR}\n    intent.removeExtra("google.message_id")`
            )
        return cfg
    })
}
