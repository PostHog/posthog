package com.posthog.code.mobile.hedgehog

import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.util.Log

class HedgehogWidgetProvider : AppWidgetProvider() {
    override fun onReceive(context: Context, intent: Intent) {
        try {
            when (intent.action) {
                HedgehogRenderer.ACTION_POKE -> poke(context, intent)
                HedgehogRenderer.ACTION_ADVANCE -> HedgehogRenderer.renderAll(context)
                else -> super.onReceive(context, intent)
            }
        } catch (e: Exception) {
            Log.e(HedgehogRenderer.TAG, "Hedgehog widget broadcast ${intent.action} failed", e)
        }
    }

    override fun onUpdate(context: Context, appWidgetManager: AppWidgetManager, appWidgetIds: IntArray) {
        appWidgetIds.forEach { HedgehogRenderer.renderOne(context, appWidgetManager, it) }
    }

    override fun onAppWidgetOptionsChanged(
        context: Context,
        appWidgetManager: AppWidgetManager,
        appWidgetId: Int,
        newOptions: Bundle,
    ) {
        HedgehogRenderer.renderOne(context, appWidgetManager, appWidgetId)
    }

    override fun onDisabled(context: Context) {
        HedgehogRenderer.cancelAlarms(context)
    }

    override fun onDeleted(context: Context, appWidgetIds: IntArray) {
        appWidgetIds.forEach { HedgehogStore.remove(context, it) }
    }

    private fun poke(context: Context, intent: Intent) {
        val id = intent.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID)
        if (id !in HedgehogRenderer.widgetIds(context)) return
        HedgehogStore.selectNext(context, id)
        // The tapped frame supplies its own index: launcher animations pause off-screen, so elapsed time cannot
        // tell us which frame is visible. Keep its position and continue the same loop in the new character.
        HedgehogRenderer.renderOne(context, AppWidgetManager.getInstance(context), id, intent.getIntExtra("frameIndex", 0))
    }
}
