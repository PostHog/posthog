package com.posthog.code.mobile.chart

import android.content.Context
import android.util.Log
import androidx.work.Worker
import androidx.work.WorkerParameters

/** One network pass for every placed chart widget, then a render. Failures keep the cache, so it never retries. */
class ChartRefreshWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        try {
            ChartWidgetRefresh.fetchShownPins(applicationContext, isStopped = { isStopped })
            if (!isStopped) ChartRenderer.renderAll(applicationContext).get()
        } catch (e: Exception) {
            Log.e("ChartWidget", "Chart widget refresh failed", e)
        }
        return Result.success()
    }
}

/** Never does anything; see `ChartWidgetRefresh.refreshAll` for why it stays queued. */
class ChartKeepEnabledWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result = Result.success()
}
