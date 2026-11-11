package com.posthog.code.mobile.chart

import org.json.JSONArray
import org.json.JSONObject

/** Field names follow the store contract in modules/chart-widget/README.md, which iOS shares. */

internal fun JSONObject.stringOrNull(key: String): String? =
    if (has(key) && !isNull(key)) optString(key).takeIf { it.isNotEmpty() } else null

internal fun JSONObject.longOrNull(key: String): Long? = (opt(key) as? Number)?.toLong()

internal fun JSONObject.doubleOrNull(key: String): Double? =
    (opt(key) as? Number)?.toDouble()?.takeIf { it.isFinite() }

private fun JSONArray?.strings(): List<String> =
    if (this == null) emptyList() else (0 until length()).mapNotNull { optString(it).takeIf { s -> s.isNotEmpty() } }

data class Credentials(
    val host: String,
    val projectId: Long,
    val projectName: String,
    val accessToken: String,
    /** Epoch ms, or null for a key that never expires. */
    val expiresAt: Long?,
    val userUuid: String?,
) {
    // A token inside its last minute would expire mid-refresh, so it counts as expired already.
    fun isExpired(now: Long): Boolean = expiresAt != null && now > expiresAt - EXPIRY_MARGIN_MS

    companion object {
        private const val EXPIRY_MARGIN_MS = 60_000L

        fun parse(json: String): Credentials? = runCatching {
            val o = JSONObject(json)
            Credentials(
                host = o.getString("host").trimEnd('/'),
                projectId = o.getLong("projectId"),
                projectName = o.optString("projectName"),
                accessToken = o.getString("accessToken"),
                expiresAt = o.longOrNull("expiresAt"),
                userUuid = o.stringOrNull("userUuid"),
            )
        }.getOrNull()
    }
}

data class CatalogPin(
    val id: String,
    val kind: String,
    val name: String,
    val subtitle: String,
    val insightId: Long?,
    val shortId: String?,
    val dashboardId: Long?,
    val eligible: Boolean,
    val number: Boolean,
    val chart: Boolean,
    val reason: String?,
    val displayMode: String? = null,
) {
    val isDashboard: Boolean get() = kind == "dashboard"
}

data class Catalog(
    val host: String,
    val projectId: Long,
    val projectName: String,
    val writtenAt: Long,
    val pins: List<CatalogPin>,
) {
    fun pin(id: String): CatalogPin? = pins.firstOrNull { it.id == id }

    companion object {
        fun parse(json: String): Catalog? = runCatching {
            val o = JSONObject(json)
            val array = o.optJSONArray("pins") ?: JSONArray()
            val pins = (0 until array.length()).mapNotNull { index ->
                val p = array.optJSONObject(index) ?: return@mapNotNull null
                val id = p.stringOrNull("id") ?: return@mapNotNull null
                CatalogPin(
                    id = id,
                    kind = p.optString("kind", "insight"),
                    name = p.stringOrNull("name") ?: "Untitled",
                    subtitle = p.optString("subtitle"),
                    insightId = p.longOrNull("insightId"),
                    shortId = p.stringOrNull("shortId"),
                    dashboardId = p.longOrNull("dashboardId"),
                    eligible = p.optBoolean("eligible", false),
                    number = p.optBoolean("number", false),
                    chart = p.optBoolean("chart", false),
                    reason = p.stringOrNull("reason"),
                    displayMode = p.stringOrNull("displayMode"),
                )
            }
            Catalog(
                host = o.optString("host").trimEnd('/'),
                projectId = o.getLong("projectId"),
                projectName = o.optString("projectName"),
                writtenAt = o.optLong("writtenAt"),
                pins = pins,
            )
        }.getOrNull()
    }
}

/**
 * The pin a placed widget shows. `projectId`, `projectName` and `pinName` are remembered at configure time, so the
 * widget can still name the pin after it leaves the catalog or the app switches project.
 */
data class WidgetConfig(
    val pinId: String,
    val extraPinIds: List<String>,
    val projectId: Long?,
    val projectName: String?,
    val pinName: String?,
) {
    fun toJson(): String = JSONObject()
        .put("pinId", pinId)
        .put("extraPinIds", JSONArray(extraPinIds))
        .apply {
            projectId?.let { put("projectId", it) }
            projectName?.let { put("projectName", it) }
            pinName?.let { put("pinName", it) }
        }
        .toString()

    companion object {
        fun parse(json: String): WidgetConfig? = runCatching {
            val o = JSONObject(json)
            WidgetConfig(
                pinId = o.getString("pinId"),
                extraPinIds = o.optJSONArray("extraPinIds").strings(),
                projectId = o.longOrNull("projectId"),
                projectName = o.stringOrNull("projectName"),
                pinName = o.stringOrNull("pinName"),
            )
        }.getOrNull()
    }
}

object ErrorKind {
    const val NETWORK = "network"
    const val AUTH = "auth"
    const val NOT_FOUND = "not_found"
    const val RATE_LIMITED = "rate_limited"
    const val BAD_DATA = "bad_data"
    /** A 200 whose `result` is null: the server has not computed the insight, and the widget never asks it to. */
    const val NO_RESULT = "no_result"
}

data class SnapshotError(val at: Long, val kind: String) {
    fun toJson(): String = JSONObject().put("at", at).put("kind", kind).toString()

    companion object {
        fun parse(json: String): SnapshotError? = runCatching {
            val o = JSONObject(json)
            SnapshotError(o.getLong("at"), o.getString("kind"))
        }.getOrNull()
    }
}

/** `value` is NaN for a bucket without a number; JSON stores it as null. */
data class SnapshotPoint(val at: String, val value: Double)

data class SnapshotSeries(val label: String, val points: List<SnapshotPoint>, val previous: Boolean)

data class SnapshotRow(val label: String, val value: String)

data class ChartSnapshot(
    val pinId: String,
    val fetchedAt: Long,
    val lastRefreshAt: String?,
    val rangeLabel: String?,
    val intervalLabel: String,
    val valueText: String?,
    val deltaPercent: Double?,
    val deltaText: String?,
    val deltaBasis: String?,
    val inProgress: Boolean,
    val series: List<SnapshotSeries>,
    val chartKind: String,
    val display: String? = null,
    val chartValueText: String? = null,
    val axisLowText: String? = null,
    val axisHighText: String? = null,
    val rows: List<SnapshotRow> = emptyList(),
) {
    val deltaSign: Int get() = deltaPercent?.let { if (it > 0) 1 else if (it < 0) -1 else 0 } ?: 0

    fun toJson(): String {
        val seriesArray = JSONArray()
        series.forEach { s ->
            val points = JSONArray()
            s.points.forEach { p ->
                points.put(JSONObject().put("at", p.at).put("value", if (p.value.isFinite()) p.value else JSONObject.NULL))
            }
            seriesArray.put(JSONObject().put("label", s.label).put("points", points).put("previous", s.previous))
        }
        return JSONObject()
            .put("version", 1)
            .put("pinId", pinId)
            .put("fetchedAt", fetchedAt)
            .put("lastRefreshAt", lastRefreshAt ?: JSONObject.NULL)
            .put("rangeLabel", rangeLabel ?: JSONObject.NULL)
            .put("intervalLabel", intervalLabel)
            .put("valueText", valueText ?: JSONObject.NULL)
            .put("deltaPercent", deltaPercent ?: JSONObject.NULL)
            .put("deltaText", deltaText ?: JSONObject.NULL)
            .put("deltaBasis", deltaBasis ?: JSONObject.NULL)
            .put("inProgress", inProgress)
            .put("series", seriesArray)
            .put("chartKind", chartKind)
            .put("chartValueText", chartValueText ?: JSONObject.NULL)
            .put("axisLowText", axisLowText ?: JSONObject.NULL)
            .put("axisHighText", axisHighText ?: JSONObject.NULL)
            .put("display", display ?: JSONObject.NULL)
            .put("rows", JSONArray(rows.map { JSONObject().put("label", it.label).put("value", it.value) }))
            .toString()
    }

    companion object {
        fun parse(json: String): ChartSnapshot? = runCatching {
            val o = JSONObject(json)
            val array = o.optJSONArray("series") ?: JSONArray()
            val series = (0 until array.length()).mapNotNull { index ->
                val s = array.optJSONObject(index) ?: return@mapNotNull null
                val pointsArray = s.optJSONArray("points") ?: JSONArray()
                val points = (0 until pointsArray.length()).mapNotNull { i ->
                    val p = pointsArray.optJSONObject(i) ?: return@mapNotNull null
                    SnapshotPoint(p.optString("at"), p.doubleOrNull("value") ?: Double.NaN)
                }
                SnapshotSeries(s.optString("label"), points, s.optBoolean("previous", false))
            }
            ChartSnapshot(
                pinId = o.getString("pinId"),
                fetchedAt = o.getLong("fetchedAt"),
                lastRefreshAt = o.stringOrNull("lastRefreshAt"),
                rangeLabel = o.stringOrNull("rangeLabel"),
                intervalLabel = o.optString("intervalLabel", "day"),
                valueText = o.stringOrNull("valueText"),
                deltaPercent = o.doubleOrNull("deltaPercent"),
                deltaText = o.stringOrNull("deltaText"),
                deltaBasis = o.stringOrNull("deltaBasis"),
                inProgress = o.optBoolean("inProgress", false),
                series = series,
                chartKind = o.optString("chartKind", "line"),
                display = o.stringOrNull("display"),
                chartValueText = o.stringOrNull("chartValueText"),
                axisLowText = o.stringOrNull("axisLowText"),
                axisHighText = o.stringOrNull("axisHighText"),
                rows = o.optJSONArray("rows")?.let { rows -> (0 until rows.length()).mapNotNull { index ->
                    rows.optJSONObject(index)?.let { SnapshotRow(it.optString("label"), it.optString("value")) }
                } } ?: emptyList(),
            )
        }.getOrNull()
    }
}

internal fun ChartSnapshot?.visibleAfter(error: SnapshotError?): ChartSnapshot? {
    if (this == null) return null
    return if (error != null && error.at >= fetchedAt &&
        (error.kind == ErrorKind.AUTH || error.kind == ErrorKind.NOT_FOUND)
    ) null else this
}

internal fun ChartSnapshot.updatedAt(): Long = lastRefreshAt?.let(DateText::parseInstant) ?: fetchedAt
