package com.posthog.code.mobile.hedgehog

import android.content.Context
import android.content.SharedPreferences

/** The SharedPreferences contract shared with the app's JavaScript, see modules/hedgehog-widget/README.md. */
object HedgehogStore {
    private const val FILE = "hedgehog_widget"
    private const val KEY_CHOREOGRAPHY = "choreography"
    private const val KEY_POKED_AT = "pokedAt"

    private fun prefs(context: Context): SharedPreferences =
        context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun choreographyJson(context: Context): String? = prefs(context).getString(KEY_CHOREOGRAPHY, null)

    // commit() rather than apply() so the widget refresh that follows reads the new script from disk-backed state.
    fun setChoreographyJson(context: Context, json: String?) {
        val editor = prefs(context).edit()
        if (json == null) editor.remove(KEY_CHOREOGRAPHY) else editor.putString(KEY_CHOREOGRAPHY, json)
        editor.commit()
    }

    fun pokedAt(context: Context): Long = prefs(context).getLong(KEY_POKED_AT, 0L)

    fun setPokedAt(context: Context, epochMs: Long) {
        prefs(context).edit().putLong(KEY_POKED_AT, epochMs).apply()
    }
}
