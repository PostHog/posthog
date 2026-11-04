package com.posthog.code.mobile.chart

import android.content.Context
import android.content.SharedPreferences
import android.util.Log
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** The store contract shared with the app's JavaScript, see modules/chart-widget/README.md. */
object ChartStore {
    private const val TAG = "ChartWidget"
    private const val FILE = "chart_widget"
    private const val SECURE_FILE = "chart_widget_secure"
    private const val KEY_CREDENTIALS = "credentials"
    private const val KEY_CATALOG = "chart.catalog"
    private const val SNAPSHOT_PREFIX = "chart.snapshot."
    private const val ERROR_PREFIX = "chart.snapshotError."
    private const val WIDGET_PREFIX = "chart.widget."

    private var secure: SharedPreferences? = null
    private var cachedCatalogJson: String? = null
    private var cachedCatalog: Catalog? = null

    private fun prefs(context: Context): SharedPreferences =
        context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    /**
     * Null when the keystore cannot open the file. A restored backup or a corrupt key fails the same way, so the file
     * is deleted and created once more; the app writes the session again on its next token change or launch.
     */
    @Synchronized
    private fun securePrefs(context: Context): SharedPreferences? {
        secure?.let { return it }
        val app = context.applicationContext
        for (attempt in 0..1) {
            try {
                val key = MasterKey.Builder(app).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
                return EncryptedSharedPreferences.create(
                    app,
                    SECURE_FILE,
                    key,
                    EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                    EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
                ).also { secure = it }
            } catch (e: Exception) {
                Log.e(TAG, "Could not open the widget credentials (attempt ${attempt + 1})", e)
                if (attempt == 0) app.deleteSharedPreferences(SECURE_FILE)
            }
        }
        return null
    }

    /** An entry the key can no longer decrypt would fail every later read and write, so the file starts over. */
    @Synchronized
    private fun resetSecure(context: Context) {
        secure = null
        context.applicationContext.deleteSharedPreferences(SECURE_FILE)
    }

    // commit() rather than apply() so the refresh that follows reads the new values.
    fun setCredentials(context: Context, json: String) {
        for (attempt in 0..1) {
            try {
                securePrefs(context)?.edit()?.putString(KEY_CREDENTIALS, json)?.commit()
                break
            } catch (e: Exception) {
                Log.e(TAG, "Could not store the widget credentials (attempt ${attempt + 1})", e)
                resetSecure(context)
            }
        }
        // A new token answers a rejected one, so the next render may show the cache again.
        val prefs = prefs(context)
        val editor = prefs.edit()
        prefs.all.forEach { (key, value) ->
            if (key.startsWith(ERROR_PREFIX) && (value as? String)?.let(SnapshotError::parse)?.kind == ErrorKind.AUTH) {
                editor.remove(key)
            }
        }
        editor.commit()
    }

    fun clearCredentials(context: Context) {
        try {
            securePrefs(context)?.edit()?.remove(KEY_CREDENTIALS)?.commit()
        } catch (e: Exception) {
            Log.e(TAG, "Could not clear the widget credentials", e)
            resetSecure(context)
        }
        val prefs = prefs(context)
        val editor = prefs.edit()
        prefs.all.keys.filter { it.startsWith(SNAPSHOT_PREFIX) || it.startsWith(ERROR_PREFIX) }.forEach { editor.remove(it) }
        editor.commit()
    }

    fun credentials(context: Context): Credentials? = try {
        securePrefs(context)?.getString(KEY_CREDENTIALS, null)?.let(Credentials::parse)
    } catch (e: Exception) {
        Log.e(TAG, "Could not read the widget credentials", e)
        resetSecure(context)
        null
    }

    fun setCatalogJson(context: Context, json: String?) {
        val editor = prefs(context).edit()
        if (json == null) editor.remove(KEY_CATALOG) else editor.putString(KEY_CATALOG, json)
        editor.commit()
    }

    @Synchronized
    fun catalog(context: Context): Catalog? {
        val json = prefs(context).getString(KEY_CATALOG, null) ?: return null
        if (json != cachedCatalogJson) {
            cachedCatalogJson = json
            cachedCatalog = Catalog.parse(json)
        }
        return cachedCatalog
    }

    fun widgetConfig(context: Context, id: Int): WidgetConfig? =
        prefs(context).getString("$WIDGET_PREFIX$id", null)?.let(WidgetConfig::parse)

    fun setWidgetConfig(
        context: Context,
        id: Int,
        pinId: String,
        extraPinIds: List<String>,
        projectId: Long? = null,
        projectName: String? = null,
        pinName: String? = null,
    ) {
        val config = WidgetConfig(pinId, extraPinIds, projectId, projectName, pinName)
        prefs(context).edit().putString("$WIDGET_PREFIX$id", config.toJson()).commit()
    }

    fun removeWidget(context: Context, id: Int) {
        val prefs = prefs(context)
        val editor = prefs.edit().remove("$WIDGET_PREFIX$id")
        val keys = prefs.all.keys
        val shown = keys.filter { it.startsWith(WIDGET_PREFIX) && it != "$WIDGET_PREFIX$id" }
            .mapNotNull { prefs.getString(it, null)?.let(WidgetConfig::parse) }
            .flatMap { listOf(it.pinId) + it.extraPinIds }
            .toSet()
        keys.forEach { key ->
            val pinId = when {
                key.startsWith(SNAPSHOT_PREFIX) -> key.removePrefix(SNAPSHOT_PREFIX)
                key.startsWith(ERROR_PREFIX) -> key.removePrefix(ERROR_PREFIX)
                else -> return@forEach
            }
            if (pinId !in shown) editor.remove(key)
        }
        editor.commit()
    }

    /** A restored home screen gives each widget a new id. */
    fun moveWidget(context: Context, from: Int, to: Int) {
        val prefs = prefs(context)
        val json = prefs.getString("$WIDGET_PREFIX$from", null) ?: return
        prefs.edit().remove("$WIDGET_PREFIX$from").putString("$WIDGET_PREFIX$to", json).commit()
    }

    fun snapshot(context: Context, pinId: String): ChartSnapshot? =
        prefs(context).getString("$SNAPSHOT_PREFIX$pinId", null)?.let(ChartSnapshot::parse)

    fun setSnapshot(context: Context, snapshot: ChartSnapshot) {
        prefs(context).edit()
            .putString("$SNAPSHOT_PREFIX${snapshot.pinId}", snapshot.toJson())
            .remove("$ERROR_PREFIX${snapshot.pinId}")
            .commit()
    }

    fun snapshotError(context: Context, pinId: String): SnapshotError? =
        prefs(context).getString("$ERROR_PREFIX$pinId", null)?.let(SnapshotError::parse)

    fun setSnapshotError(context: Context, pinId: String, error: SnapshotError) {
        prefs(context).edit().putString("$ERROR_PREFIX$pinId", error.toJson()).commit()
    }
}
