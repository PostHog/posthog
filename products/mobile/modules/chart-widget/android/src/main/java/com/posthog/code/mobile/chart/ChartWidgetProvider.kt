package com.posthog.code.mobile.chart

import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.util.Log

class ChartWidgetProvider : AppWidgetProvider() {
    /** Catches everything, because an exception thrown from a broadcast receiver crashes the whole app process. */
    override fun onReceive(context: Context, intent: Intent) {
        try {
            super.onReceive(context, intent)
        } catch (e: Exception) {
            Log.e(ChartRenderer.TAG, "Chart widget broadcast ${intent.action} failed", e)
        }
    }

    override fun onUpdate(context: Context, appWidgetManager: AppWidgetManager, appWidgetIds: IntArray) {
        ChartWidgetRefresh.refreshAll(context)
    }

    override fun onAppWidgetOptionsChanged(context: Context, appWidgetManager: AppWidgetManager, appWidgetId: Int, newOptions: Bundle) {
        val pendingResult = goAsync()
        try {
            ChartRenderer.renderOne(context, appWidgetManager, appWidgetId) { pendingResult?.finish() }
        } catch (e: Exception) {
            pendingResult?.finish()
            throw e
        }
    }

    override fun onDeleted(context: Context, appWidgetIds: IntArray) {
        appWidgetIds.forEach { ChartStore.removeWidget(context, it) }
    }

    override fun onDisabled(context: Context) {
        ChartWidgetRefresh.cancel(context)
    }

    override fun onRestored(context: Context, oldWidgetIds: IntArray, newWidgetIds: IntArray) {
        oldWidgetIds.zip(newWidgetIds).forEach { (from, to) -> ChartStore.moveWidget(context, from, to) }
    }
}
