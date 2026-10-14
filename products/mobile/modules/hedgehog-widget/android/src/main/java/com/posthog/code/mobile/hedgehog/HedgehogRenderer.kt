package com.posthog.code.mobile.hedgehog

import android.app.AlarmManager
import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Parcel
import android.util.Log
import android.widget.RemoteViews
import java.util.Locale
import kotlin.math.roundToInt

object HedgehogRenderer {
    const val TAG = "HedgehogWidget"
    const val ACTION_POKE = "com.posthog.code.mobile.HEDGEHOG_POKE"
    const val ACTION_ADVANCE = "com.posthog.code.mobile.HEDGEHOG_ADVANCE"

    private const val FALLBACK_SPRITE = "hog_idle_00"
    private const val REQUEST_POKE = 1
    private const val REQUEST_OPEN = 2
    private const val REQUEST_ADVANCE = 3

    // A 4x2 widget on a phone, used when the launcher has not reported a size yet.
    private const val DEFAULT_WIDTH_DP = 250
    private const val DEFAULT_HEIGHT_DP = 110

    private val spriteIds = HashMap<String, Int>()
    private var cachedJson: String? = null
    private var cachedChoreography: Choreography? = null

    fun widgetIds(context: Context): IntArray =
        AppWidgetManager.getInstance(context)
            .getAppWidgetIds(ComponentName(context, HedgehogWidgetProvider::class.java))

    /** Catches everything, because an exception thrown from a broadcast receiver crashes the whole app process. */
    fun renderAll(context: Context, ids: IntArray = widgetIds(context)) {
        try {
            val manager = AppWidgetManager.getInstance(context)
            val choreography = choreography(context)
            val now = System.currentTimeMillis()
            val reacting = isReacting(context, choreography, now)
            for (id in ids) {
                manager.updateAppWidget(id, build(context, manager, id, choreography, reacting, now))
            }
            if (ids.isNotEmpty()) {
                scheduleAdvance(context, if (reacting) null else choreography.nextSlotStartMs(now))
            }
        } catch (e: Exception) {
            Log.e(TAG, "Could not render the hedgehog widget", e)
        }
    }

    fun renderOne(context: Context, manager: AppWidgetManager, id: Int) {
        try {
            val choreography = choreography(context)
            val now = System.currentTimeMillis()
            manager.updateAppWidget(id, build(context, manager, id, choreography, isReacting(context, choreography, now), now))
        } catch (e: Exception) {
            Log.e(TAG, "Could not render hedgehog widget $id", e)
        }
    }

    @Synchronized
    fun choreography(context: Context): Choreography {
        val json = HedgehogStore.choreographyJson(context) ?: return FallbackChoreography.value
        if (json != cachedJson) {
            cachedJson = json
            cachedChoreography = Choreography.parse(json)
        }
        return cachedChoreography ?: FallbackChoreography.value
    }

    fun reactionTicks(choreography: Choreography): List<Tick> =
        choreography.reactionTicks.ifEmpty { FallbackChoreography.value.reactionTicks }

    /**
     * Reaction ticks are authored at x 0.5 facing right. Shift them to where the loop starts, which is also where
     * every loop comes to rest, so the hedgehog reacts on the spot instead of jumping to the centre.
     */
    private fun reactionInPlace(choreography: Choreography, anchor: Tick): List<Tick> =
        reactionTicks(choreography).map {
            it.copy(x = (it.x + anchor.x - 0.5f).coerceIn(0f, 1f), facing = anchor.facing)
        }

    private fun isReacting(context: Context, choreography: Choreography, now: Long): Boolean {
        val elapsed = now - HedgehogStore.pokedAt(context)
        return elapsed >= 0 && elapsed < reactionTicks(choreography).size.toLong() * choreography.tickMs
    }

    private fun build(
        context: Context,
        manager: AppWidgetManager,
        id: Int,
        choreography: Choreography,
        reacting: Boolean,
        now: Long,
    ): RemoteViews {
        val pkg = context.packageName
        val resources = context.resources
        val density = resources.displayMetrics.density
        val options = manager.getAppWidgetOptions(id)
        // Portrait size: the launcher reports min width and max height for the portrait cell grid.
        val widthPx = (options.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH).takeIf { it > 0 } ?: DEFAULT_WIDTH_DP) * density
        val heightPx = (options.getInt(AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT).takeIf { it > 0 } ?: DEFAULT_HEIGHT_DP) * density
        val spritePx = resources.getDimensionPixelSize(R.dimen.hedgehog_sprite_size)
        val floorPx = resources.getDimensionPixelSize(R.dimen.hedgehog_floor_inset)
        val maxLeft = (widthPx - spritePx).coerceAtLeast(0f)
        val maxBottom = (heightPx - spritePx).coerceAtLeast(0f)
        // In a widget too short for the sprite, the feet sink below the floor line instead of the head clipping.
        val minBottom = minOf(floorPx.toFloat(), maxBottom)

        val loop = choreography.loopAt(now)
        val ticks = (if (reacting) reactionInPlace(choreography, loop.first()) else loop).take(Choreography.MAX_TICKS)
        val poke = pokeIntent(context)
        val root = RemoteViews(pkg, R.layout.hedgehog_widget)
        root.removeAllViews(R.id.hedgehog_flipper)
        for (tick in ticks) {
            val frame = RemoteViews(pkg, R.layout.hedgehog_frame)
            frame.setImageViewResource(R.id.hedgehog_sprite, spriteId(context, tick))
            val left = (tick.x * widthPx - spritePx / 2f).coerceIn(0f, maxLeft).roundToInt()
            val bottom = (floorPx + tick.y * (heightPx - floorPx)).coerceIn(minBottom, maxBottom).roundToInt()
            frame.setViewPadding(R.id.hedgehog_frame, left, 0, 0, bottom)
            // The flipper hides every frame except the one on screen, so a tap reaches the sprite where it is now.
            frame.setOnClickPendingIntent(R.id.hedgehog_sprite, poke)
            root.addView(R.id.hedgehog_flipper, frame)
        }
        root.setInt(R.id.hedgehog_flipper, "setFlipInterval", choreography.tickMs)
        root.setDisplayedChild(R.id.hedgehog_flipper, 0)
        // A tap that misses the sprite falls through the frames, which are not clickable, to the root.
        openAppIntent(context)?.let { root.setOnClickPendingIntent(R.id.hedgehog_root, it) }

        if (Log.isLoggable(TAG, Log.DEBUG)) {
            val parcel = Parcel.obtain()
            try {
                root.writeToParcel(parcel, 0)
                Log.d(TAG, "widget $id: ${ticks.size} ticks, ${widthPx.roundToInt()}x${heightPx.roundToInt()}px, parcel ${parcel.dataSize()} bytes, reacting=$reacting")
            } finally {
                parcel.recycle()
            }
        }
        return root
    }

    @Synchronized
    private fun spriteId(context: Context, tick: Tick): Int {
        val name = String.format(Locale.US, "hog_%s_%02d%s", tick.pose, tick.frame, if (tick.facing == Facing.LEFT) "_l" else "")
        return spriteIds.getOrPut(name) {
            val id = context.resources.getIdentifier(name, "drawable", context.packageName)
            if (id != 0) id else context.resources.getIdentifier(FALLBACK_SPRITE, "drawable", context.packageName)
        }
    }

    private fun pokeIntent(context: Context): PendingIntent =
        PendingIntent.getBroadcast(
            context,
            REQUEST_POKE,
            Intent(context, HedgehogWidgetProvider::class.java).setAction(ACTION_POKE),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

    private fun openAppIntent(context: Context): PendingIntent? {
        val launch = context.packageManager.getLaunchIntentForPackage(context.packageName) ?: return null
        return PendingIntent.getActivity(
            context,
            REQUEST_OPEN,
            launch,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
    }

    private fun advanceIntent(context: Context): PendingIntent =
        PendingIntent.getBroadcast(
            context,
            REQUEST_ADVANCE,
            Intent(context, HedgehogWidgetProvider::class.java).setAction(ACTION_ADVANCE),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

    /**
     * Wakes the provider at the next loop slot so the routine changes during the day.
     * The alarm is inexact and does not wake the device, because nobody sees the widget while the screen is off.
     */
    private fun scheduleAdvance(context: Context, atMs: Long?) {
        if (atMs == null) return
        val alarms = context.getSystemService(AlarmManager::class.java) ?: return
        alarms.set(AlarmManager.RTC, atMs, advanceIntent(context))
    }

    /** Ends a reaction too long to wait for inside the receiver. */
    fun scheduleReactionEnd(context: Context, atMs: Long) {
        val alarms = context.getSystemService(AlarmManager::class.java) ?: return
        val pending = advanceIntent(context)
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S || alarms.canScheduleExactAlarms()) {
            alarms.setExactAndAllowWhileIdle(AlarmManager.RTC, atMs, pending)
        } else {
            alarms.setWindow(AlarmManager.RTC, atMs, 60_000L, pending)
        }
    }

    fun cancelAlarms(context: Context) {
        context.getSystemService(AlarmManager::class.java)?.cancel(advanceIntent(context))
    }
}
