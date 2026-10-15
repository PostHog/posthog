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
        val movement = loop.flatMapIndexed { index, tick ->
            val next = loop[(index + 1) % loop.size]
            List(substeps) { part ->
                val progress = part.toFloat() / substeps
                tick.copy(x = tick.x + (next.x - tick.x) * progress, y = tick.y + (next.y - tick.y) * progress)
            }
        }
        val character = HedgehogStore.selected(context, id)
        var facing = movement.first().facing
        val ticks = movement.mapIndexed { index, tick ->
            val previous = movement[(index + movement.size - 1) % movement.size]
            val distance = tick.x - previous.x
            if (tick.pose == "walk" && kotlin.math.abs(distance) > 0.001f) {
                facing = if (distance < 0) Facing.LEFT else Facing.RIGHT
            }
            tick.copy(hoggie = character, facing = facing, bubble = null)
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
            val bottom = (floorPx + tick.y * (heightPx - floorPx)).coerceIn(minBottom, maxBottom).roundToInt()
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
