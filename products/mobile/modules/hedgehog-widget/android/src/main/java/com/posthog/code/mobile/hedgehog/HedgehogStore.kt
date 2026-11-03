package com.posthog.code.mobile.hedgehog

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject

/** The SharedPreferences contract shared with the app's JavaScript, see modules/hedgehog-widget/README.md. */
object HedgehogStore {
    private const val FILE = "hedgehog_widget"
    private const val KEY_CHOREOGRAPHY = "choreography"
    // Bump when loops change meaning, so a placed widget drops its pinned loop once and picks up the new script.
    private const val KEY_LOOP = "loop.v2"
    private const val KEY_LEGACY_LOOP = "loop"

    private fun prefs(context: Context): SharedPreferences =
        context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun choreographyJson(context: Context): String? = prefs(context).getString(KEY_CHOREOGRAPHY, null)

    // commit() rather than apply() so the widget refresh that follows reads the new script from disk-backed state.
    fun setChoreographyJson(context: Context, json: String?) {
        val editor = prefs(context).edit()
        if (json == null) editor.remove(KEY_CHOREOGRAPHY) else editor.putString(KEY_CHOREOGRAPHY, json)
        editor.commit()
    }

    private val characters = listOf("coffee_cup", "party", "wizard", "explorer", "superhero", "reading", "float")

    fun selected(context: Context, id: Int): String? = prefs(context).getString("selectedHog.$id", null)

    fun selectNext(context: Context, id: Int) {
        val next = (characters.indexOf(selected(context, id)) + 1) % characters.size
        prefs(context).edit().putString("selectedHog.$id", characters[next]).commit()
    }

    // Pin the loop while a widget is placed. Daily sync and launcher refreshes must not restart a ViewFlipper.
    fun loop(context: Context, id: Int): List<Tick>? = runCatching {
        val json = prefs(context).getString("$KEY_LOOP.$id", null) ?: return null
        val array = JSONArray(json)
        (0 until array.length()).map { index ->
            val tick = array.getJSONObject(index)
            Tick(tick.getString("pose"), tick.getInt("frame"), tick.getDouble("x").toFloat(),
                tick.getDouble("y").toFloat(), Facing.valueOf(tick.getString("facing")))
        }.takeIf { it.isNotEmpty() }
    }.getOrNull()

    fun saveLoop(context: Context, id: Int, ticks: List<Tick>) {
        val array = JSONArray()
        ticks.forEach { tick ->
            array.put(JSONObject().put("pose", tick.pose).put("frame", tick.frame)
                .put("x", tick.x).put("y", tick.y).put("facing", tick.facing.name))
        }
        prefs(context).edit().putString("$KEY_LOOP.$id", array.toString()).remove("$KEY_LEGACY_LOOP.$id").commit()
    }

    fun remove(context: Context, id: Int) {
        prefs(context).edit().remove("$KEY_LOOP.$id").remove("$KEY_LEGACY_LOOP.$id").remove("selectedHog.$id").commit()
    }
}
