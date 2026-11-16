package com.posthog.code.mobile.chart

import android.content.Context
import android.content.SharedPreferences
import android.util.Log
import org.json.JSONObject
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
    private const val KEY_RETRY_AT = "chart.retryAt"
    private var sessionGeneration = 0L

    internal data class Session(val generation: Long, val credentials: Credentials)

    private const val WIDGET_PREFIX = "chart.widget."

    private var secure: SharedPreferences? = null
    private var cachedCatalogJson: String? = null
    private var cachedCatalog: Catalog? = null

    @Synchronized
    private fun prefs(context: Context): SharedPreferences {
        val store = requireNotNull(securePrefs(context)) { "Widget storage unavailable" }
        val legacy = context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)
        if (legacy.all.isNotEmpty()) {
            val editor = store.edit()
            legacy.all.forEach { (key, value) ->
                if (key.startsWith(WIDGET_PREFIX) && key.removePrefix(WIDGET_PREFIX).toIntOrNull() != null &&
                    !store.contains(key) && value is String) {
                    WidgetConfig.parse(value)?.let { editor.putString(key, it.toJson()) }
                }
            }
            check(editor.commit()) { "Could not migrate widget selections" }
            check(legacy.edit().clear().commit()) { "Could not clear legacy widget storage" }
        }
        return store
    }

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
    @Synchronized
    fun setCredentials(context: Context, json: String) {
        val previous = credentials(context)
        sessionGeneration += 1
        for (attempt in 0..1) {
            try {
                val store = checkNotNull(securePrefs(context)) { "Widget credential storage is unavailable" }
                check(store.edit().putString(KEY_CREDENTIALS, json).commit()) { "Could not persist widget credentials" }
                break
            } catch (e: Exception) {
                Log.e(TAG, "Could not store the widget credentials (attempt ${attempt + 1})", e)
                resetSecure(context)
                if (attempt == 1) throw IllegalStateException("Could not store widget credentials", e)
            }
        }
        val next = credentials(context)
        if (previous?.host != next?.host || previous?.projectId != next?.projectId || previous?.userUuid != next?.userUuid) {
            clearSnapshots(context)
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

    @Synchronized
    fun clearCredentials(context: Context) {
        sessionGeneration += 1
        try {
            securePrefs(context)?.edit()?.remove(KEY_CREDENTIALS)?.commit()
        } catch (e: Exception) {
            Log.e(TAG, "Could not clear the widget credentials", e)
            resetSecure(context)
        }
        clearSnapshots(context)
    }

    private fun clearSnapshots(context: Context) {
        val prefs = prefs(context)
        val editor = prefs.edit().remove(KEY_RETRY_AT)
        prefs.all.keys.filter { it.startsWith(SNAPSHOT_PREFIX) || it.startsWith(ERROR_PREFIX) }.forEach { editor.remove(it) }
        editor.commit()
    }

    @Synchronized
    fun credentials(context: Context): Credentials? = try {
        securePrefs(context)?.getString(KEY_CREDENTIALS, null)?.let(Credentials::parse)
    } catch (e: Exception) {
        Log.e(TAG, "Could not read the widget credentials", e)
        resetSecure(context)
        null
    }

    @Synchronized
    fun setCatalogJson(context: Context, json: String?) {
        val editor = prefs(context).edit()
        if (json == null) {
            editor.remove(KEY_CATALOG)
            clearSnapshots(context)
        } else {
            val old = catalog(context)
            val next = JSONObject(json)
            val pins = next.optJSONArray("pins")
            val selected = selectedPinIds(context).toSet()
            val allowed = (0 until (pins?.length() ?: 0)).mapNotNull { pins?.optJSONObject(it) }
                .filter { it.optBoolean("eligible") }.map { it.optString("id") }.toSet().intersect(selected)
            retainSnapshots(context, allowed)
            for (index in 0 until (pins?.length() ?: 0)) {
                val pin = pins?.optJSONObject(index) ?: continue
                val id = pin.optString("id")
                val previous = old?.pin(id)
                val changed = old?.host != next.optString("host").trimEnd('/') || old?.projectId != next.optLong("projectId") || previous == null || previous.kind != pin.optString("kind", "insight") || previous.insightId != pin.longOrNull("insightId") ||
                    previous.shortId != pin.stringOrNull("shortId") || previous.dashboardId != pin.longOrNull("dashboardId") ||
                    previous.displayMode != pin.stringOrNull("displayMode")
                if (changed) {
                    editor.remove("$SNAPSHOT_PREFIX$id").remove("$ERROR_PREFIX$id")
                }
                pin.optJSONObject("snapshot")?.takeIf { id in allowed }?.let { snapshot ->
                    val cached = if (changed) null else ChartStore.snapshot(context, id)
                    if (snapshot.optLong("fetchedAt") >= (cached?.fetchedAt ?: 0L)) {
                        editor.putString("$SNAPSHOT_PREFIX$id", snapshot.toString()).remove("$ERROR_PREFIX$id")
                    }
                }
                pin.remove("snapshot")
            }
            editor.putString(KEY_CATALOG, next.toString())
        }
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
        retainSnapshots(context, selectedPinIds(context).toSet())
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
        if (ChartRenderer.widgetIds(context).none { it != id }) clearCredentials(context)
    }

    fun selectedPinIds(context: Context): List<String> = ChartRenderer.widgetIds(context).flatMap { id ->
        widgetConfig(context, id)?.let { listOf(it.pinId) + it.extraPinIds } ?: emptyList()
    }.distinct()

    fun retainSnapshots(context: Context, selected: Set<String>) {
        val store = prefs(context)
        val editor = store.edit()
        store.all.keys.forEach { key ->
            val prefix = listOf(SNAPSHOT_PREFIX, ERROR_PREFIX).firstOrNull { key.startsWith(it) } ?: return@forEach
            if (key.removePrefix(prefix) !in selected) editor.remove(key)
        }
        editor.commit()
    }

    /** A restored home screen gives each widget a new id. */
    fun moveWidget(context: Context, from: Int, to: Int) {
        val prefs = prefs(context)
        val json = prefs.getString("$WIDGET_PREFIX$from", null) ?: return
        prefs.edit().remove("$WIDGET_PREFIX$from").putString("$WIDGET_PREFIX$to", json).commit()
    }

    @Synchronized
    internal fun session(context: Context): Session? = credentials(context)?.let { Session(sessionGeneration, it) }

    internal fun retryAt(context: Context): Long = prefs(context).getLong(KEY_RETRY_AT, 0L)

    @Synchronized
    internal fun commitFetch(
        context: Context,
        expectedSession: Session,
        expectedCatalog: Catalog,
        pinIds: List<String>,
        outcome: ChartFetcher.Outcome,
        isStopped: () -> Boolean,
        startedAt: Long,
    ): Boolean {
        if (isStopped() || expectedSession != session(context) || expectedCatalog != catalog(context) ||
            !selectedPinIds(context).containsAll(pinIds)) return false
        val editor = prefs(context).edit()
        when (outcome) {
            is ChartFetcher.Outcome.Success -> {
                setSnapshot(context, outcome.snapshot)
                return true
            }
            is ChartFetcher.Outcome.Failure -> {
                val now = System.currentTimeMillis()
                val error = SnapshotError(startedAt, outcome.kind)
                pinIds.forEach {
                    if ((snapshot(context, it)?.fetchedAt ?: 0L) > startedAt) return@forEach
                    editor.putString("$ERROR_PREFIX$it", error.toJson())
                    if (outcome.kind == ErrorKind.AUTH || outcome.kind == ErrorKind.NOT_FOUND) {
                        editor.remove("$SNAPSHOT_PREFIX$it")
                    }
                }
                if (outcome.kind == ErrorKind.RATE_LIMITED) editor.putLong(KEY_RETRY_AT, now + outcome.retryAfterMs)
            }
        }
        return editor.commit()
    }

    fun snapshot(context: Context, pinId: String): ChartSnapshot? =
        prefs(context).getString("$SNAPSHOT_PREFIX$pinId", null)?.let(ChartSnapshot::parse)

    @Synchronized
    fun setSnapshot(context: Context, snapshot: ChartSnapshot) {
        if ((ChartStore.snapshot(context, snapshot.pinId)?.fetchedAt ?: 0L) > snapshot.fetchedAt) return
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
