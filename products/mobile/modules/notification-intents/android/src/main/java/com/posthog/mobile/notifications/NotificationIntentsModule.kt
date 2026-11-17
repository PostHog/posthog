package com.posthog.mobile.notifications

import android.content.Context
import android.content.Intent
import android.os.Bundle
import expo.modules.kotlin.exception.Exceptions
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import expo.modules.notifications.notifications.NotificationManager
import expo.modules.notifications.notifications.model.NotificationResponse
import expo.modules.notifications.service.NotificationsService
import org.json.JSONObject

object NotificationIntentStore {
    private fun preferences(context: Context) =
        context.getSharedPreferences("posthog_notification_intents_v2", Context.MODE_PRIVATE)

    private val routingKeys = listOf("type", "report_id", "project_id", "taskId", "projectId", "notificationKind")

    fun handleIntent(context: Context, intent: Intent, initial: Boolean) {
        if (intent.component?.className == "com.posthog.mobile.notifications.NotificationTapActivity") {
            val response = NotificationsService.getNotificationResponseFromOpenIntent(intent)
            if (capture(context, intent, initial, response)) {
                if (response != null) {
                    NotificationManager.onNotificationResponseReceived(response)
                } else {
                    intent.extras?.let { NotificationManager.onNotificationResponseFromExtras(Bundle(it)) }
                }
            }
        }
        intent.removeExtra("google.message_id")
    }

    // Android restores the original launch intent even after a newer tap has replaced it in the activity.
    @Synchronized
    private fun capture(context: Context, intent: Intent, initial: Boolean, response: NotificationResponse?): Boolean {
        val extras = intent.extras ?: return false
        val remoteId = extras.getString("google.message_id")
        val id = remoteId ?: response?.notification?.notificationRequest?.identifier ?: return false
        val preferences = preferences(context)
        if (preferences.getString("initial_message_id", null) == id) return false
        val source = response?.notification?.notificationRequest?.content?.body ?: try {
            JSONObject(extras.getString("body") ?: "")
        } catch (_: org.json.JSONException) {
            JSONObject().apply {
                for (key in routingKeys) {
                    if (extras.containsKey(key)) put(key, extras.get(key))
                }
            }
        }
        val data = JSONObject()
        for (key in routingKeys) {
            if (source.has(key)) data.put(key, source.get(key))
        }
        val pending = JSONObject().put("identifier", id).put("data", data.toString())
        val editor = preferences.edit().putString("pending_response", pending.toString())
        if (initial) editor.putString("initial_message_id", id)
        // Persist before handing off to Expo; its in-memory queue cannot survive process death.
        editor.commit()
        return true
    }

    @Synchronized
    fun pending(context: Context): Map<String, String>? {
        val json = preferences(context).getString("pending_response", null) ?: return null
        val pending = JSONObject(json)
        return mapOf("identifier" to pending.getString("identifier"), "data" to pending.getString("data"))
    }

    @Synchronized
    fun acknowledge(context: Context, identifier: String) {
        if (pending(context)?.get("identifier") == identifier) {
            preferences(context).edit().remove("pending_response").commit()
        }
    }
}

class NotificationIntentsModule : Module() {
    override fun definition() = ModuleDefinition {
        Name("NotificationIntents")
        Function("getPending") { NotificationIntentStore.pending(context()) }
        Function("acknowledge") { identifier: String -> NotificationIntentStore.acknowledge(context(), identifier) }
    }

    private fun context(): Context =
        appContext.reactContext?.applicationContext ?: throw Exceptions.ReactContextLost()
}
