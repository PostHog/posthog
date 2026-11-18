package com.posthog.code.mobile.hedgehog

import android.app.AlarmManager
import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Parcel
import android.util.Log
import android.util.TypedValue
import android.widget.RemoteViews
import java.util.Locale
import kotlin.math.abs
import kotlin.math.roundToInt

object HedgehogRenderer {
    const val TAG = "HedgehogWidget"
    const val ACTION_POKE = "com.posthog.code.mobile.HEDGEHOG_POKE"
    const val ACTION_ADVANCE = "com.posthog.code.mobile.HEDGEHOG_ADVANCE"

    private const val FALLBACK_SPRITE = "hog_idle_00"
    private const val REQUEST_OPEN = 2
    private const val REQUEST_ADVANCE = 3

    // A 4x2 widget on a phone, used when the launcher has not reported a size yet.
    private const val DEFAULT_WIDTH_DP = 250
    private const val DEFAULT_HEIGHT_DP = 110

    // Frame counts of the bundled hog_<pose>_<NN> sheets.
    private val FRAME_COUNTS = mapOf("idle" to 25, "walk" to 11, "jump" to 10, "wave" to 26, "action" to 16, "fall" to 9)
    private const val MAX_FRAME_ADVANCE = 6
    private const val MIN_TRAVEL = 0.001f

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
            for (id in ids) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S || HedgehogStore.loop(context, id) == null) {
                    manager.updateAppWidget(id, build(context, manager, id, choreography, now))
                }
            }
            cancelAlarms(context)
        } catch (e: Exception) {
            Log.e(TAG, "Could not render the hedgehog widget", e)
        }
    }

    fun renderOne(context: Context, manager: AppWidgetManager, id: Int, frameIndex: Int? = null) {
        try {
            val choreography = choreography(context)
            val now = System.currentTimeMillis()
            manager.updateAppWidget(id, build(context, manager, id, choreography, now, frameIndex))
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

    private fun build(
        context: Context,
        manager: AppWidgetManager,
        id: Int,
        choreography: Choreography,
        now: Long,
        frameIndex: Int? = null,
    ): RemoteViews {
        val pkg = context.packageName
        val resources = context.resources
        val density = resources.displayMetrics.density
        val options = manager.getAppWidgetOptions(id)
        // Portrait size: the launcher reports min width and max height for the portrait cell grid.
        val widthPx = (options.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH).takeIf { it > 0 } ?: DEFAULT_WIDTH_DP) * density
        val heightPx = (options.getInt(AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT).takeIf { it > 0 } ?: DEFAULT_HEIGHT_DP) * density
        val floorPx = resources.getDimensionPixelSize(R.dimen.hedgehog_floor_inset)

        val loop = HedgehogStore.loop(context, id) ?: choreography.loopAt(now)
            .take(Choreography.MAX_TICKS).map { it.copy(hoggie = null, bubble = null) }
            .also { HedgehogStore.saveLoop(context, id, it) }
        val substeps = ((choreography.tickMs + 32) / 33).coerceIn(1, 4)
        val character = HedgehogStore.selected(context, id)
        val ticks = loop.flatMapIndexed { index, tick ->
            val next = loop[(index + 1) % loop.size]
            List(substeps) { part ->
                val progress = part.toFloat() / substeps
                // Substeps that rise toward an airborne tick are off the ground, so they show `fall` like the simulation.
                val takingOff = part > 0 && next.pose == "fall" && tick.pose != "fall"
                tick.copy(
                    pose = if (takingOff) next.pose else tick.pose,
                    frame = if (takingOff) fallFrame(next, substeps - part) else substepFrame(tick, next, part, substeps),
                    x = tick.x + (next.x - tick.x) * progress,
                    y = tick.y + (next.y - tick.y) * progress,
                    facing = substepFacing(tick, next, part),
                    hoggie = character,
                    bubble = null,
                )
            }
        }
        val root = RemoteViews(pkg, R.layout.hedgehog_widget)
        root.removeAllViews(R.id.hedgehog_flipper)
        for ((index, tick) in ticks.withIndex()) {
            val largeIllustration = heightPx >= 140 * density
            val spritePx = resources.getDimensionPixelSize(if (largeIllustration) R.dimen.hoggie_sprite_size else R.dimen.hedgehog_sprite_size)
            // The same centre/lift envelope for every character prevents a tap from shifting its feet.
            val envelope = spritePx
            val margin = envelope / 2f
            val artInset = envelope * 0.125f
            val minBottom = minOf(floorPx.toFloat(), (heightPx - envelope).coerceAtLeast(0f))
            val maxBottom = (heightPx - envelope + artInset).coerceAtLeast(minBottom)
            val stableFrames = Build.VERSION.SDK_INT >= Build.VERSION_CODES.S
            val frame = RemoteViews(pkg, if (!stableFrames && largeIllustration) R.layout.hedgehog_hoggie_frame else R.layout.hedgehog_frame)
            if (stableFrames) {
                frame.setViewLayoutWidth(R.id.hedgehog_sprite, spritePx.toFloat(), TypedValue.COMPLEX_UNIT_PX)
                frame.setViewLayoutHeight(R.id.hedgehog_sprite, spritePx.toFloat(), TypedValue.COMPLEX_UNIT_PX)
            }
            frame.setImageViewResource(R.id.hedgehog_sprite, spriteId(context, tick))
            val left = (margin + tick.x * (widthPx - 2 * margin).coerceAtLeast(0f) - spritePx / 2f).roundToInt()
            // `y` 1 is the top of the rise that keeps the sprite inside the widget, so a jump apex is not clipped flat.
            val bottom = (floorPx + tick.y * (maxBottom - floorPx).coerceAtLeast(0f)).coerceIn(minBottom, maxBottom).roundToInt()
            frame.setViewPadding(R.id.hedgehog_frame, left, 0, 0, bottom)
            // The flipper hides every frame except the one on screen, so a tap reaches the sprite where it is now.
            frame.setOnClickPendingIntent(R.id.hedgehog_sprite, pokeIntent(context, id, index))
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                // Reapply the same child views in place, retaining the launcher's actual displayed frame.
                root.addStableView(R.id.hedgehog_flipper, frame, index)
            } else {
                root.addView(R.id.hedgehog_flipper, frame)
            }
        }
        root.setInt(R.id.hedgehog_flipper, "setFlipInterval", choreography.tickMs / substeps)
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S && frameIndex != null) {
            root.setDisplayedChild(R.id.hedgehog_flipper, Math.floorMod(frameIndex, ticks.size))
        }
        // A tap that misses the sprite falls through the frames, which are not clickable, to the root.
        openAppIntent(context)?.let { root.setOnClickPendingIntent(R.id.hedgehog_root, it) }

        if (Log.isLoggable(TAG, Log.DEBUG)) {
            val parcel = Parcel.obtain()
            try {
                root.writeToParcel(parcel, 0)
                Log.d(TAG, "widget $id: ${ticks.size} ticks, ${widthPx.roundToInt()}x${heightPx.roundToInt()}px, parcel ${parcel.dataSize()} bytes")
            } finally {
                parcel.recycle()
            }
        }
        return root
    }

    /**
     * Ticks sample a 30 fps sprite sheet, so consecutive ticks of one pose skip 3 or 4 frames. Substeps fill in the
     * skipped frames. A pose change or a larger gap is a restarted animation, so those substeps hold the tick's frame.
     */
    private fun substepFrame(tick: Tick, next: Tick, part: Int, substeps: Int): Int {
        val count = FRAME_COUNTS[tick.pose] ?: return tick.frame
        if (part == 0 || next.pose != tick.pose) return tick.frame
        val advance = Math.floorMod(next.frame - tick.frame, count)
        if (advance > MAX_FRAME_ADVANCE) return tick.frame
        return (tick.frame + (advance * part + substeps / 2) / substeps) % count
    }

    /** The `fall` frame shown `framesBefore` substeps before the next tick, at about one sprite frame per substep. */
    private fun fallFrame(next: Tick, framesBefore: Int): Int =
        Math.floorMod(next.frame - framesBefore, FRAME_COUNTS.getValue("fall"))

    /**
     * The script's facing is the simulation's facing at the tick. When it changes before the next tick, the hedgehog
     * turned somewhere in between, so the substeps face the way they move instead of walking backwards.
     */
    private fun substepFacing(tick: Tick, next: Tick, part: Int): Facing {
        if (part == 0 || next.facing == tick.facing || abs(next.x - tick.x) <= MIN_TRAVEL) return tick.facing
        return if (next.x < tick.x) Facing.LEFT else Facing.RIGHT
    }

    @Synchronized
    private fun hoggieId(context: Context, tick: Tick): Int {
        val name = "hoggie_${tick.hoggie}${if (tick.facing == Facing.LEFT) "_l" else ""}"
        return spriteIds.getOrPut(name) { context.resources.getIdentifier(name, "drawable", context.packageName) }
    }

    @Synchronized
    private fun spriteId(context: Context, tick: Tick): Int {
        if (tick.hoggie != null) {
            val id = hoggieId(context, tick)
            if (id != 0) return id
        }
        val name = String.format(Locale.US, "hog_%s_%02d%s", tick.pose, tick.frame, if (tick.facing == Facing.LEFT) "_l" else "")
        return spriteIds.getOrPut(name) {
            val id = context.resources.getIdentifier(name, "drawable", context.packageName)
            if (id != 0) id else context.resources.getIdentifier(FALLBACK_SPRITE, "drawable", context.packageName)
        }
    }

    private fun pokeIntent(context: Context, id: Int, frameIndex: Int): PendingIntent =
        PendingIntent.getBroadcast(
            context,
            0,
            Intent(context, HedgehogWidgetProvider::class.java).setAction(ACTION_POKE)
                .setData(Uri.parse("posthog-widget://poke/$id/$frameIndex"))
                .putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id)
                .putExtra("frameIndex", frameIndex),
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

    fun cancelAlarms(context: Context) {
        context.getSystemService(AlarmManager::class.java)?.cancel(advanceIntent(context))
    }
}
