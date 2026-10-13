package com.posthog.code.mobile.hedgehog

import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

enum class Facing { LEFT, RIGHT }

data class Tick(
    val pose: String,
    val frame: Int,
    val x: Float,
    val y: Float,
    val facing: Facing,
)

data class Choreography(
    val startsAtMs: Long,
    val tickMs: Int,
    val loopMinutes: Int,
    val loops: List<List<Tick>>,
    val reactionTicks: List<Tick>,
) {
    fun loopAt(nowMs: Long): List<Tick> {
        val slot = Math.floorDiv(nowMs - startsAtMs, loopMinutes * MS_PER_MINUTE)
        return loops[Math.floorMod(slot, loops.size.toLong()).toInt()]
    }

    fun nextSlotStartMs(nowMs: Long): Long {
        val slotMs = loopMinutes * MS_PER_MINUTE
        return startsAtMs + (Math.floorDiv(nowMs - startsAtMs, slotMs) + 1) * slotMs
    }

    val reactionDurationMs: Long
        get() = reactionTicks.size.toLong() * tickMs

    companion object {
        const val MAX_TICKS = 120
        private const val MS_PER_MINUTE = 60_000L
        private const val TAG = "HedgehogWidget"
        private val POSES = setOf("idle", "walk", "jump", "wave", "action", "fall")

        /** Returns null for anything this renderer cannot play, so the caller falls back. */
        fun parse(json: String): Choreography? =
            try {
                parseOrThrow(JSONObject(json))
            } catch (e: Exception) {
                Log.w(TAG, "Ignoring an unreadable choreography", e)
                null
            }

        private fun parseOrThrow(root: JSONObject): Choreography? {
            val version = root.optInt("version", -1)
            if (version != 1) {
                Log.w(TAG, "Ignoring choreography version $version")
                return null
            }
            val loopsJson = root.optJSONArray("loops") ?: return null
            val loops = (0 until loopsJson.length())
                .mapNotNull { loopsJson.optJSONArray(it)?.let(::parseTicks) }
                .filter { it.isNotEmpty() }
            if (loops.isEmpty()) {
                Log.w(TAG, "Choreography has no playable loops")
                return null
            }
            val reaction = root.optJSONObject("reaction")?.optJSONArray("ticks")?.let(::parseTicks).orEmpty()
            return Choreography(
                startsAtMs = parseIsoMs(root.optString("startsAt")) ?: 0L,
                tickMs = root.optInt("tickMs", DEFAULT_TICK_MS).coerceIn(40, 2_000),
                loopMinutes = root.optInt("loopMinutes", DEFAULT_LOOP_MINUTES).coerceIn(1, 24 * 60),
                loops = loops,
                reactionTicks = reaction,
            )
        }

        private fun parseTicks(array: JSONArray): List<Tick> =
            (0 until minOf(array.length(), MAX_TICKS)).mapNotNull { index ->
                val tick = array.optJSONObject(index) ?: return@mapNotNull null
                val pose = tick.optString("pose")
                if (pose !in POSES) return@mapNotNull null
                Tick(
                    pose = pose,
                    frame = tick.optInt("frame", 0).coerceAtLeast(0),
                    x = unit(tick.optDouble("x", 0.5)),
                    y = unit(tick.optDouble("y", 0.0)),
                    facing = if (tick.optString("facing") == "left") Facing.LEFT else Facing.RIGHT,
                )
            }

        private fun unit(value: Double): Float = if (value.isNaN()) 0f else value.toFloat().coerceIn(0f, 1f)

        // java.time needs API 26 and the app supports API 24, so parse the two shapes Date.toISOString() and Swift emit.
        private fun parseIsoMs(value: String): Long? {
            for (pattern in listOf("yyyy-MM-dd'T'HH:mm:ss.SSSX", "yyyy-MM-dd'T'HH:mm:ssX")) {
                val format = SimpleDateFormat(pattern, Locale.US).apply { timeZone = TimeZone.getTimeZone("UTC") }
                runCatching { format.parse(value)?.time }.getOrNull()?.let { return it }
            }
            Log.w(TAG, "Unreadable startsAt '$value', using the epoch")
            return null
        }
    }
}

const val DEFAULT_TICK_MS = 120
const val DEFAULT_LOOP_MINUTES = 10

/** Played until the app has written a choreography: walk right, wave, walk back. */
object FallbackChoreography {
    private const val WALK_FRAMES = 11
    private const val WAVE_FRAMES = 26
    private const val WALK_TICKS = 30
    private const val LEFT_X = 0.2f
    private const val RIGHT_X = 0.8f

    val value: Choreography by lazy {
        Choreography(
            startsAtMs = 0L,
            tickMs = DEFAULT_TICK_MS,
            loopMinutes = DEFAULT_LOOP_MINUTES,
            loops = listOf(loop()),
            reactionTicks = (0 until WAVE_FRAMES).map { Tick("wave", it, 0.5f, 0f, Facing.RIGHT) },
        )
    }

    private fun loop(): List<Tick> {
        val walkRight = (0 until WALK_TICKS).map {
            Tick("walk", it % WALK_FRAMES, lerp(LEFT_X, RIGHT_X, it / WALK_TICKS.toFloat()), 0f, Facing.RIGHT)
        }
        val wave = (0 until WAVE_FRAMES).map { Tick("wave", it, RIGHT_X, 0f, Facing.LEFT) }
        val walkBack = (0 until WALK_TICKS).map {
            Tick("walk", it % WALK_FRAMES, lerp(RIGHT_X, LEFT_X, it / WALK_TICKS.toFloat()), 0f, Facing.LEFT)
        }
        val rest = (0 until 20).map { Tick("idle", it, LEFT_X, 0f, Facing.RIGHT) }
        return walkRight + wave + walkBack + rest
    }

    private fun lerp(from: Float, to: Float, t: Float): Float = from + (to - from) * t
}
