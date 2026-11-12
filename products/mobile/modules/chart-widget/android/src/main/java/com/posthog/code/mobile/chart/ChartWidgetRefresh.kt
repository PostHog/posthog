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

    /** A new request replaces the queued pass so it uses the latest session and catalog. */
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
    internal fun fetchShownPins(
        context: Context,
        isStopped: () -> Boolean,
        fetch: (Context, Credentials, CatalogPin) -> ChartFetcher.Outcome = { app, credentials, pin ->
            ChartFetcher.fetch(app, credentials, pin)
        },
    ) {
        val session = ChartStore.session(context) ?: return
        val credentials = session.credentials
        val now = System.currentTimeMillis()
        if (credentials.isExpired(now) || now < ChartStore.retryAt(context)) return
        val catalog = ChartStore.catalog(context)?.takeIf {
            it.projectId == credentials.projectId && it.host == credentials.host
        } ?: return
        val pins = ChartRenderer.widgetIds(context).asList()
            .mapNotNull { ChartStore.widgetConfig(context, it) }
            .flatMap { listOf(it.pinId) + it.extraPinIds }
            .distinct()
            .mapNotNull { catalog.pin(it)?.takeIf { pin -> pin.eligible } }
        for ((index, pin) in pins.withIndex()) {
            if (isStopped() || session != ChartStore.session(context)) return
            val startedAt = System.currentTimeMillis()
            val outcome = fetch(context, credentials, pin)
            val stopsPass = outcome is ChartFetcher.Outcome.Failure &&
                (outcome.kind == ErrorKind.AUTH || outcome.kind == ErrorKind.RATE_LIMITED)
            val affected = if (stopsPass) pins.drop(index).map { it.id } else listOf(pin.id)
            if (!ChartStore.commitFetch(context, session, catalog, affected, outcome, isStopped, startedAt) || stopsPass) return
        }
    }
}
