package com.posthog.code.mobile.chart

import android.app.Activity
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProviderInfo
import android.content.ComponentName
import android.content.Context
import android.content.BroadcastReceiver
import android.content.ContextWrapper
import android.content.Intent
import android.content.SharedPreferences
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import java.util.concurrent.TimeUnit
import java.util.concurrent.CountDownLatch
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowBroadcastPendingResult
import org.robolectric.util.ReflectionHelpers
import org.robolectric.util.ReflectionHelpers.ClassParameter

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class ChartWidgetRefreshTest {
    private lateinit var context: Context

    private fun credentials(token: String = "test-token"): String = JSONObject()
        .put("host", "https://example.com").put("projectId", 1).put("projectName", "Example")
        .put("accessToken", token).put("userUuid", "example-user").toString()

    private fun snapshot(pin: String = "first"): ChartSnapshot = ChartSnapshot(
        pin, 1000L, null, null, "day", "42", null, null, null, false, emptyList(), "line",
    )

    @Before
    fun setUp() {
        context = RuntimeEnvironment.getApplication()
        val secure = context.getSharedPreferences("test-credentials", Context.MODE_PRIVATE)
        secure.edit().clear().commit()
        ReflectionHelpers.setStaticField(ChartStore::class.java, "secure", secure)
        context.getSharedPreferences("chart_widget", Context.MODE_PRIVATE).edit().clear().commit()
        ChartStore.setCredentials(context, credentials())
        ChartStore.setCatalogJson(context, """{"host":"https://example.com","projectId":1,"pins":[
            {"id":"first","insightId":1,"eligible":true},
            {"id":"second","insightId":2,"eligible":true}
        ]}""")
        val provider = ComponentName(context, ChartWidgetProvider::class.java)
        shadowOf(AppWidgetManager.getInstance(context)).addBoundWidget(1, AppWidgetProviderInfo().apply {
            this.provider = provider
        })
        ChartStore.setWidgetConfig(context, 1, "first", listOf("second"))
    }

    private fun doneButton(activity: Activity): Button {
        fun descendants(view: View): Sequence<View> = sequence {
            yield(view)
            if (view is ViewGroup) {
                for (index in 0 until view.childCount) yieldAll(descendants(view.getChildAt(index)))
            }
        }
        return descendants(activity.findViewById(android.R.id.content)).filterIsInstance<Button>()
            .single { it.text == context.getString(R.string.chart_widget_configure_done) }
    }

    @Test
    fun configurationRejectsMissingUnknownAndOtherProvidersWidgetIds() {
        shadowOf(AppWidgetManager.getInstance(context)).addBoundWidget(2, AppWidgetProviderInfo().apply {
            provider = ComponentName("com.example.other", "com.example.other.WidgetProvider")
        })
        for (id in listOf(AppWidgetManager.INVALID_APPWIDGET_ID, 999, 2)) {
            val intent = Intent(AppWidgetManager.ACTION_APPWIDGET_CONFIGURE)
                .putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id)
            val controller = Robolectric.buildActivity(ChartWidgetConfigureActivity::class.java, intent).create()
            val activity = controller.get()
            assertTrue(activity.isFinishing)
            assertEquals(Activity.RESULT_CANCELED, shadowOf(activity).resultCode)
            assertNull(ChartStore.widgetConfig(context, id))
            controller.destroy()
        }
    }

    @Test
    fun configurationReturnsOnlyTheConfirmedWidgetId() {
        for (signedIn in listOf(true, false)) {
            if (!signedIn) ChartStore.clearCredentials(context)
            val intent = Intent(AppWidgetManager.ACTION_APPWIDGET_CONFIGURE)
                .putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, 1)
            val controller = Robolectric.buildActivity(ChartWidgetConfigureActivity::class.java, intent).create()
            val activity = controller.get()
            assertFalse(activity.isFinishing)
            assertEquals(Activity.RESULT_CANCELED, shadowOf(activity).resultCode)
            doneButton(activity).performClick()
            assertTrue(activity.isFinishing)
            assertEquals(Activity.RESULT_OK, shadowOf(activity).resultCode)
            val result = shadowOf(activity).resultIntent
            assertEquals(setOf(AppWidgetManager.EXTRA_APPWIDGET_ID), result.extras!!.keySet())
            assertEquals(1, result.getIntExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, -1))
            assertEquals("first", ChartStore.widgetConfig(context, 1)?.pinId)
            controller.destroy()
        }
    }

    @Test
    fun configurationRechecksWidgetOwnershipBeforeSaving() {
        val intent = Intent(AppWidgetManager.ACTION_APPWIDGET_CONFIGURE)
            .putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, 1)
        val controller = Robolectric.buildActivity(ChartWidgetConfigureActivity::class.java, intent).create()
        val activity = controller.get()
        ChartStore.removeWidget(context, 1)
        shadowOf(AppWidgetManager.getInstance(context)).addBoundWidget(1, AppWidgetProviderInfo().apply {
            provider = ComponentName("com.example.other", "com.example.other.WidgetProvider")
        })
        doneButton(activity).performClick()
        assertEquals(Activity.RESULT_CANCELED, shadowOf(activity).resultCode)
        assertNull(ChartStore.widgetConfig(context, 1))
        controller.destroy()
    }

    @Test
    fun discardsResultsFromAnEndedOrReplacedSession() {
        for (change in listOf<() -> Unit>(
            { ChartStore.clearCredentials(context) },
            { ChartStore.setCredentials(context, credentials("new-token")) },
            { ChartStore.clearCredentials(context); ChartStore.setCredentials(context, credentials()) },
        )) {
            ChartStore.setCredentials(context, credentials())
            ChartWidgetRefresh.fetchShownPins(context, { false }) { _, _, _ ->
                change()
                ChartFetcher.Outcome.Success(snapshot())
            }
            assertNull(ChartStore.snapshot(context, "first"))
        }
    }

    @Test
    fun discardsCanceledFetchAndErrorsFromAReplacedToken() {
        var stopped = false
        ChartWidgetRefresh.fetchShownPins(context, { stopped }) { _, _, _ ->
            stopped = true
            ChartFetcher.Outcome.Success(snapshot())
        }
        assertNull(ChartStore.snapshot(context, "first"))
        ChartWidgetRefresh.fetchShownPins(context, { false }) { _, _, _ ->
            ChartStore.setCredentials(context, credentials("new-token"))
            ChartFetcher.Outcome.Failure(ErrorKind.AUTH)
        }
        assertNull(ChartStore.snapshotError(context, "first"))
        assertNull(ChartStore.snapshotError(context, "second"))
    }

    @Test
    fun rejectsAnotherHostsCatalogAndAnUpdatedCatalog() {
        val catalog = ChartStore.catalog(context)!!
        ChartStore.setCatalogJson(context, """{"host":"https://other.example.com","projectId":1,"pins":[{"id":"first","eligible":true}]}""")
        var calls = 0
        ChartWidgetRefresh.fetchShownPins(context, { false }) { _, _, _ ->
            calls++
            ChartFetcher.Outcome.Success(snapshot())
        }
        assertEquals(0, calls)
        ChartStore.setCatalogJson(context, """{"host":"https://example.com","projectId":1,"pins":[]}""")
        assertFalse(ChartStore.commitFetch(context, ChartStore.session(context)!!, catalog, listOf("first"),
            ChartFetcher.Outcome.Success(snapshot()), { false }, 1000L))
        assertNull(ChartStore.snapshot(context, "first"))
    }

    @Test
    fun backgroundReadsPreserveNewerAppSnapshots() {
        val newer = snapshot().copy(fetchedAt = 2000L, valueText = "84")
        ChartStore.setSnapshot(context, newer)
        ChartWidgetRefresh.fetchShownPins(context, { false }) { _, _, pin ->
            ChartFetcher.Outcome.Success(snapshot(pin.id))
        }
        assertEquals(newer, ChartStore.snapshot(context, "first"))
        assertEquals(snapshot("second"), ChartStore.snapshot(context, "second"))
    }

    @Test
    fun delayedFailuresPreserveSnapshotsWrittenAfterTheRequestStarted() {
        val session = ChartStore.session(context)!!
        val catalog = ChartStore.catalog(context)!!
        val newer = snapshot().copy(fetchedAt = 2000L, valueText = "84")
        for (kind in listOf(ErrorKind.AUTH, ErrorKind.NOT_FOUND, ErrorKind.NETWORK)) {
            ChartStore.setSnapshot(context, newer)
            ChartStore.commitFetch(context, session, catalog, listOf("first"),
                ChartFetcher.Outcome.Failure(kind), { false }, 1000L)
            assertEquals(newer, ChartStore.snapshot(context, "first"))
            assertNull(ChartStore.snapshotError(context, "first"))
        }
        ChartStore.commitFetch(context, session, catalog, listOf("first"),
            ChartFetcher.Outcome.Failure(ErrorKind.NOT_FOUND), { false }, 3000L)
        assertNull(ChartStore.snapshot(context, "first"))
    }

    @Test
    fun migratesLegacySelectionsWithoutOverwritingNewSelectionsOrCopyingResults() {
        val legacy = context.getSharedPreferences("chart_widget", Context.MODE_PRIVATE)
        val original = WidgetConfig("legacy", listOf("extra"), 1, "Old project", "Old pin").toJson()
        legacy.edit().putString("chart.widget.1", original).putString("chart.widget.2", original)
            .putString("chart.snapshot.legacy", "old values").putString("chart.widget.invalid", original).commit()
        assertEquals("first", ChartStore.widgetConfig(context, 1)?.pinId)
        assertEquals(WidgetConfig.parse(original), ChartStore.widgetConfig(context, 2))
        assertNull(ChartStore.snapshot(context, "legacy"))
        assertTrue(legacy.all.isEmpty())
    }

    @Test
    fun catalogChangesDiscardOnlySnapshotsForChangedTargets() {
        val original = JSONObject().put("host", "https://example.com").put("projectId", 1)
            .put("pins", org.json.JSONArray().put(JSONObject()
                .put("id", "first").put("kind", "dashboard").put("dashboardId", 10).put("insightId", 1).put("eligible", true)))
        val replacements = listOf(
            original.toString(),
            JSONObject(original.toString()).apply { getJSONArray("pins").getJSONObject(0).put("name", "Renamed") }.toString(),
            JSONObject(original.toString()).apply { getJSONArray("pins").getJSONObject(0).put("kind", "insight") }.toString(),
            JSONObject(original.toString()).apply { getJSONArray("pins").getJSONObject(0).put("insightId", 2) }.toString(),
            JSONObject(original.toString()).apply { getJSONArray("pins").getJSONObject(0).put("dashboardId", 11) }.toString(),
            JSONObject(original.toString()).put("projectId", 2).toString(),
            JSONObject(original.toString()).put("host", "https://other.example.com").toString(),
            JSONObject(original.toString()).put("pins", org.json.JSONArray()).toString(),
            null,
        )
        for ((index, replacement) in replacements.withIndex()) {
            ChartStore.setCatalogJson(context, original.toString())
            ChartStore.setSnapshot(context, snapshot())
            ChartStore.setSnapshotError(context, "first", SnapshotError(2000L, ErrorKind.NETWORK))
            ChartStore.setCatalogJson(context, replacement)
            assertEquals("snapshot for case $index", index < 2, ChartStore.snapshot(context, "first") != null)
            assertEquals("error for case $index", index < 2, ChartStore.snapshotError(context, "first") != null)
        }
    }

    @Test
    fun credentialWritesReportUnavailableStorageAndFailedCommits() {
        for (unavailable in listOf(true, false)) {
            val backing = context.getSharedPreferences("test-credentials", Context.MODE_PRIVATE)
            val failing = object : SharedPreferences by backing {
                override fun edit(): SharedPreferences.Editor = object : SharedPreferences.Editor by backing.edit() {
                    override fun putString(key: String?, value: String?): SharedPreferences.Editor = this
                    override fun commit(): Boolean = false
                }
            }
            ReflectionHelpers.setStaticField(ChartStore::class.java, "secure", if (unavailable) null else failing)
            val wrapper = object : ContextWrapper(context) {
                override fun getApplicationContext(): Context = this
                override fun getSharedPreferences(name: String, mode: Int): SharedPreferences {
                    if (name == "chart_widget_secure") throw IllegalStateException("Storage unavailable")
                    return super.getSharedPreferences(name, mode)
                }
            }
            assertThrows(IllegalStateException::class.java) { ChartStore.setCredentials(wrapper, credentials("replacement")) }
        }
    }

    @Test
    fun resizeKeepsBroadcastPendingUntilTheWidgetIsUpdated() {
        val started = CountDownLatch(1)
        val release = CountDownLatch(1)
        val wrapper = object : ContextWrapper(context) {
            override fun getApplicationContext(): Context = this
            override fun getSharedPreferences(name: String, mode: Int): SharedPreferences {
                if (name == "chart_widget") {
                    started.countDown()
                    check(release.await(10, TimeUnit.SECONDS))
                }
                return super.getSharedPreferences(name, mode)
            }
        }
        val receiver = ChartWidgetProvider()
        val pending = ReflectionHelpers.callStaticMethod<BroadcastReceiver.PendingResult>(
            ShadowBroadcastPendingResult::class.java, "create",
            ClassParameter.from(Int::class.javaPrimitiveType, 0),
            ClassParameter.from(String::class.java, null),
            ClassParameter.from(Bundle::class.java, null),
            ClassParameter.from(Boolean::class.javaPrimitiveType, false),
        )
        ReflectionHelpers.setField(receiver, "mPendingResult", pending)
        val intent = Intent(AppWidgetManager.ACTION_APPWIDGET_OPTIONS_CHANGED)
            .putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, 1)
            .putExtra(AppWidgetManager.EXTRA_APPWIDGET_OPTIONS, Bundle())
        try {
            receiver.onReceive(wrapper, intent)
            assertTrue(started.await(10, TimeUnit.SECONDS))
            assertTrue(shadowOf(receiver).wentAsync())
            assertFalse(shadowOf(pending).future.isDone)
        } finally {
            release.countDown()
        }
        shadowOf(pending).future.get(10, TimeUnit.SECONDS)
        assertNotNull(shadowOf(AppWidgetManager.getInstance(context)).getViewFor(1))
    }

    @Test
    fun rateLimitStopsThePassAndSurvivesLaterRefreshes() {
        var calls = 0
        val fetch: (Context, Credentials, CatalogPin) -> ChartFetcher.Outcome = { _, _, _ ->
            calls++
            ChartFetcher.Outcome.Failure(ErrorKind.RATE_LIMITED, 120_000L)
        }
        val before = System.currentTimeMillis()
        ChartWidgetRefresh.fetchShownPins(context, { false }, fetch)
        ChartWidgetRefresh.fetchShownPins(context, { false }, fetch)
        assertEquals(1, calls)
        assertTrue(ChartStore.retryAt(context) >= before + 120_000L)
        assertEquals(ErrorKind.RATE_LIMITED, ChartStore.snapshotError(context, "second")?.kind)
        context.getSharedPreferences("test-credentials", Context.MODE_PRIVATE).edit().putLong("chart.retryAt", 0L).commit()
        ChartWidgetRefresh.fetchShownPins(context, { false }, fetch)
        assertEquals(2, calls)
    }

    @Test
    fun honorsRetryAfterWithAMinimumCooldown() {
        val now = 1_000_000L
        assertEquals(120_000L, ChartFetcher.retryAfterMs("120", now))
        assertEquals(120_000L, ChartFetcher.retryAfterMs("Thu, 01 Jan 1970 00:18:40 GMT", now))
        for (value in listOf(null, "invalid", "0", "-5")) {
            assertEquals(60_000L, ChartFetcher.retryAfterMs(value, now))
        }
    }

    @Test
    fun rendersOutsideTheCallingThread() {
        var renderingThread: Thread? = null
        val wrapper = object : ContextWrapper(context) {
            override fun getApplicationContext(): Context = this
            override fun getSystemService(name: String): Any? {
                if (name == Context.APPWIDGET_SERVICE) renderingThread = Thread.currentThread()
                return super.getSystemService(name)
            }
        }
        ChartRenderer.renderAll(wrapper).get(10, TimeUnit.SECONDS)
        assertNotNull(renderingThread)
        assertNotEquals(Thread.currentThread(), renderingThread)
    }

    @Test
    fun largeWidgetShowsTheAgeOfItsOldestVisibleTile() {
        val now = System.currentTimeMillis()
        val cached = snapshot("second").copy(fetchedAt = now - 3 * 60 * 60_000L)
        ChartStore.setSnapshot(context, snapshot().copy(fetchedAt = now))
        ChartStore.setSnapshot(context, cached)
        ChartStore.setSnapshotError(context, "second", SnapshotError(now, ErrorKind.NETWORK))
        val manager = AppWidgetManager.getInstance(context)
        manager.updateAppWidgetOptions(1, Bundle().apply {
            putInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH, 320)
            putInt(AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT, 400)
        })
        fun rendered(): View {
            ChartRenderer.renderOne(context, manager, 1).get(10, TimeUnit.SECONDS)
            return shadowOf(manager).getViewFor(1)
        }
        val view = rendered()
        assertEquals(context.getString(R.string.chart_widget_updated_hours, 3),
            view.findViewById<TextView>(R.id.chart_updated).text.toString())
        assertEquals(View.VISIBLE, view.findViewById<View>(R.id.chart_tile_1_value).visibility)
        for (kind in listOf(ErrorKind.AUTH, ErrorKind.NOT_FOUND)) {
            ChartStore.setSnapshotError(context, "second", SnapshotError(now, kind))
            val hidden = rendered()
            assertEquals(View.GONE, hidden.findViewById<View>(R.id.chart_tile_1_value).visibility)
            assertEquals(View.GONE, hidden.findViewById<View>(R.id.chart_tile_1_frame).visibility)
            assertEquals(context.getString(R.string.chart_widget_updated_just_now),
                hidden.findViewById<TextView>(R.id.chart_updated).text.toString())
        }
    }

    @Test
    fun onlyNewerAccessErrorsHideCachedTiles() {
        val cached = snapshot()
        for (kind in listOf(ErrorKind.AUTH, ErrorKind.NOT_FOUND)) {
            assertNull(cached.visibleAfter(SnapshotError(1000L, kind)))
            assertEquals(cached, cached.visibleAfter(SnapshotError(999L, kind)))
        }
        for (kind in listOf(ErrorKind.NETWORK, ErrorKind.RATE_LIMITED, ErrorKind.NO_RESULT)) {
            assertEquals(cached, cached.visibleAfter(SnapshotError(2000L, kind)))
        }
        assertEquals(1000L, cached.updatedAt())
        assertEquals(0L, cached.copy(lastRefreshAt = "1970-01-01T00:00:00Z").updatedAt())
    }
    @Test
    fun storesOnlySelectedSnapshotsInTheProtectedStoreAndClearsRemovedSelections() {
        val raw = context.getSharedPreferences("chart_widget", Context.MODE_PRIVATE)
        raw.edit().putString("chart.snapshot.legacy", "private result").commit()
        ChartStore.setCatalogJson(context, """{"host":"https://example.com","projectId":1,"pins":[
            {"id":"first","insightId":1,"eligible":true,"snapshot":${snapshot().toJson()}},
            {"id":"unselected","insightId":3,"eligible":true,"snapshot":${snapshot("unselected").toJson()}}
        ]}""")
        assertEquals(snapshot(), ChartStore.snapshot(context, "first"))
        assertNull(ChartStore.snapshot(context, "unselected"))
        assertTrue(raw.all.isEmpty())
        assertFalse(context.getSharedPreferences("test-credentials", Context.MODE_PRIVATE).getString("chart.catalog", "")!!.contains("snapshot"))
        for (kind in listOf(ErrorKind.AUTH, ErrorKind.NOT_FOUND)) {
            ChartStore.setSnapshot(context, snapshot())
            ChartWidgetRefresh.fetchShownPins(context, { false }) { _, _, _ -> ChartFetcher.Outcome.Failure(kind) }
            assertNull(ChartStore.snapshot(context, "first"))
        }
        ChartStore.retainSnapshots(context, emptySet())
        assertNull(ChartStore.snapshot(context, "first"))
        ChartStore.removeWidget(context, 1)
        assertNull(ChartStore.credentials(context))
    }

}
