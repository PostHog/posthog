package com.posthog.code.mobile.chart

import android.content.Context
import android.util.Log
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

object ChartWidgetRefresh {
    private const val TAG = "ChartWidget"
    private const val REFRESH_WORK = "chart-widget-refresh"
    private const val KEEP_ENABLED_WORK = "chart-widget-keep-enabled"
    private const val KEEP_ENABLED_DAYS = 3650L

    /**
     * Renders every placed widget from the cache now, then queues one network pass off the main thread. A new call
     * replaces a queued pass, so the newest credentials and catalog win.
     */
    fun refreshAll(context: Context) {
        val app = context.applicationContext
        ChartRenderer.renderAll(app)
        try {
            if (ChartRenderer.widgetIds(app).isEmpty()) return
            val credentials = ChartStore.credentials(app)
            if (credentials == null || credentials.isExpired(System.currentTimeMillis())) return
            val workManager = WorkManager.getInstance(app)
            // WorkManager disables its reschedule receiver when no work is pending. That component change makes the
            // system send APPWIDGET_UPDATE again, which would queue a new pass forever, so one far-off job stays queued.
            workManager.enqueueUniqueWork(
                KEEP_ENABLED_WORK,
                ExistingWorkPolicy.KEEP,
                OneTimeWorkRequestBuilder<ChartKeepEnabledWorker>().setInitialDelay(KEEP_ENABLED_DAYS, TimeUnit.DAYS).build(),
            )
            val request = OneTimeWorkRequestBuilder<ChartRefreshWorker>()
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            workManager.enqueueUniqueWork(REFRESH_WORK, ExistingWorkPolicy.REPLACE, request)
        } catch (e: Exception) {
            Log.e(TAG, "Could not queue the chart widget refresh", e)
        }
    }

    fun cancel(context: Context) {
        try {
            val workManager = WorkManager.getInstance(context.applicationContext)
            workManager.cancelUniqueWork(REFRESH_WORK)
            workManager.cancelUniqueWork(KEEP_ENABLED_WORK)
        } catch (e: Exception) {
            Log.e(TAG, "Could not cancel the chart widget refresh", e)
        }
    }

    /**
     * Reads each distinct pin that a placed widget shows, once, and stores the snapshot or the error. A rejected token
     * fails every other pin too, so the pass stops there and marks the rest.
     */
    internal fun fetchShownPins(context: Context, isStopped: () -> Boolean) {
        val credentials = ChartStore.credentials(context) ?: return
        val now = System.currentTimeMillis()
        if (credentials.isExpired(now)) return
        val catalog = ChartStore.catalog(context)?.takeIf { it.projectId == credentials.projectId } ?: return
        val pins = ChartRenderer.widgetIds(context).asList()
            .mapNotNull { ChartStore.widgetConfig(context, it) }
            .flatMap { listOf(it.pinId) + it.extraPinIds }
            .distinct()
            .mapNotNull { catalog.pin(it)?.takeIf { pin -> pin.eligible } }
        for ((index, pin) in pins.withIndex()) {
            if (isStopped()) return
            when (val outcome = ChartFetcher.fetch(context, credentials, pin)) {
                is ChartFetcher.Outcome.Success -> ChartStore.setSnapshot(context, outcome.snapshot)
                is ChartFetcher.Outcome.Failure -> {
                    val error = SnapshotError(System.currentTimeMillis(), outcome.kind)
                    if (outcome.kind == ErrorKind.AUTH) {
                        pins.drop(index).forEach { ChartStore.setSnapshotError(context, it.id, error) }
                        return
                    }
                    ChartStore.setSnapshotError(context, pin.id, error)
                }
            }
        }
    }
}
