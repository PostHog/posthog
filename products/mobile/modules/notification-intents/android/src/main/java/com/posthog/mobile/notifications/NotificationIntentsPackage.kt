package com.posthog.mobile.notifications

import android.app.Application
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import expo.modules.core.interfaces.ApplicationLifecycleListener
import expo.modules.core.interfaces.Package

class NotificationIntentsPackage : Package {
    override fun createApplicationLifecycleListeners(context: Context): List<ApplicationLifecycleListener> =
        listOf(object : ApplicationLifecycleListener {
            override fun onCreate(application: Application) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    val manager = application.getSystemService(NotificationManager::class.java)
                    // The manifest opt-out does not revoke delegation initialized by an older binary.
                    if (manager.notificationDelegate == "com.google.android.gms") {
                        manager.setNotificationDelegate(null)
                    }
                }
            }
        })
}
