package com.posthog.code.mobile.hedgehog

import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log

class HedgehogWidgetProvider : AppWidgetProvider() {
    override fun onReceive(context: Context, intent: Intent) {
        try {
            when (intent.action) {
                HedgehogRenderer.ACTION_POKE -> poke(context)
                HedgehogRenderer.ACTION_ADVANCE -> HedgehogRenderer.renderAll(context)
                else -> super.onReceive(context, intent)
            }
        } catch (e: Exception) {
            Log.e(HedgehogRenderer.TAG, "Hedgehog widget broadcast ${intent.action} failed", e)
        }
    }

    override fun onUpdate(context: Context, appWidgetManager: AppWidgetManager, appWidgetIds: IntArray) {
        HedgehogRenderer.renderAll(context, appWidgetIds)
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

    private fun poke(context: Context) {
        val pokedAt = System.currentTimeMillis()
        HedgehogStore.setPokedAt(context, pokedAt)
        HedgehogRenderer.renderAll(context)

        // ViewFlipper always loops, so the reaction must be swapped for the normal loop once it has played once.
        val choreography = HedgehogRenderer.choreography(context)
        val durationMs = HedgehogRenderer.reactionTicks(choreography).size.toLong() * choreography.tickMs
        if (durationMs > MAX_HELD_BROADCAST_MS) {
            HedgehogRenderer.scheduleReactionEnd(context, pokedAt + durationMs)
            return
        }
        // Holding the broadcast keeps the process alive until the reaction ends, which an inexact alarm cannot promise.
        val pending = goAsync()
        Handler(Looper.getMainLooper()).postDelayed({
            try {
                // A newer tap restarted the reaction and owns the next render.
                if (HedgehogStore.pokedAt(context) == pokedAt) HedgehogRenderer.renderAll(context)
            } finally {
                pending.finish()
            }
        }, durationMs)
    }

    private companion object {
        // Background broadcasts may run for about 60 s before an ANR; stay far below that.
        const val MAX_HELD_BROADCAST_MS = 9_000L
    }
}
