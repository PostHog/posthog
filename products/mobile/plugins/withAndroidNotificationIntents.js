const { withMainActivity } = require('expo/config-plugins')

// Expo SDK 57 drops onNewIntent while expo-updates is loading the app. Hand FCM taps to its
// notification queue before that delegate can drop them: https://github.com/expo/expo/issues/49254.
const INTENT_HANDLER = `
  override fun onNewIntent(intent: android.content.Intent) {
    com.posthog.mobile.notifications.NotificationIntentStore.handleIntent(this, intent, false)
    setIntent(intent)
    super.onNewIntent(intent)
  }
`

// Replay suppression and the pending tap have separate lifetimes: routing acknowledges only the pending tap.
const INITIAL_INTENT = `
    com.posthog.mobile.notifications.NotificationIntentStore.handleIntent(this, intent, true)
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
            .replace(CREATE_ANCHOR, `${INITIAL_INTENT}\n    ${CREATE_ANCHOR}`)
        return cfg
    })
}
