package com.posthog.mobile.notifications

import android.content.Intent
import com.google.firebase.messaging.RemoteMessage
import expo.modules.notifications.service.ExpoFirebaseMessagingService

class NotificationMessagingService : ExpoFirebaseMessagingService() {
    override fun handleIntent(intent: Intent) {
        if (intent.action == "com.google.android.c2dm.intent.RECEIVE") {
            val notification = intent.extras?.let { RemoteMessage(it).notification }
            if (notification != null && notification.clickAction.isNullOrEmpty() && notification.link == null) {
                // Firebase creates this PendingIntent as our UID, so it can open the private alias.
                intent.putExtra("gcm.n.click_action", "com.posthog.mobile.notifications.OPEN_FCM_NOTIFICATION")
            }
        }
        super.handleIntent(intent)
    }
}
