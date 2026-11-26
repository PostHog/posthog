package com.posthog.code.mobile.chart

import org.json.JSONArray
import org.json.JSONObject
import java.math.BigDecimal
import java.math.MathContext
import java.math.RoundingMode
import java.text.DecimalFormat
import java.text.DecimalFormatSymbols
import java.util.Calendar
import java.util.Locale
import java.util.TimeZone
import kotlin.math.abs
import kotlin.math.floor
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.min

class BadDataException(message: String) : Exception(message)

/**
 * Turns a `TrendsQuery` insight response into a widget snapshot. Mirrors `trendsEntries`, `seriesViews`, `pointsOf`,
 * `compareOf`, `numberParts` and `inProgressFrom` in `src/model/adapters/insightSnapshot.ts`, value formatting in
 * `src/model/adapters/insightFormatting.ts`, and the labels in `src/features/views/snapshotChart.ts` and `rangePresets.ts`.
 */
object TrendsParser {
    const val MAX_SERIES = 5
    const val MAX_POINTS = 60

    private val BAR_DISPLAYS = setOf("ActionsBar", "ActionsStackedBar", "ActionsUnstackedBar")
    private val INTERVALS = setOf("hour", "day", "week", "month")
    private val INTERVAL_MS = mapOf("hour" to 3_600_000L, "day" to 86_400_000L, "week" to 7 * 86_400_000L, "month" to 31 * 86_400_000L)
    // Distinct-user math counts a person once per bucket, so only these add up over a window.
    private val SUMMABLE_MATH = setOf(null, "total", "sum", "first_time_for_user", "first_matching_event_for_user")
    private const val BREAKDOWN_OTHER = "\$\$_posthog_breakdown_other_\$\$"
    private const val BREAKDOWN_NULL = "\$\$_posthog_breakdown_null_\$\$"

    private class Point(val at: String, val value: Double)
    private class Delta(val change: Double, val percent: Double?, val points: Boolean, val compare: Boolean, val previousAt: String?)
    private class NumberParts(val value: Double, val delta: Delta?)

    internal class ValueFormat(
        val style: String?,
        val prefix: String,
        val suffix: String,
        val decimalPlaces: Int?,
        val minDecimalPlaces: Int?,
    )

    fun parse(response: JSONObject, pinId: String, fetchedAt: Long): ChartSnapshot {
        val query = response.optJSONObject("query") ?: throw BadDataException("no query")
        val source = query.optJSONObject("source") ?: query
        if (source.optString("kind") != "TrendsQuery") throw BadDataException("not a trends query")
        val result = response.opt("result") as? JSONArray ?: throw BadDataException("no result")
        val entries = (0 until result.length()).mapNotNull { result.optJSONObject(it) }
        val interval = source.optString("interval").takeIf { it in INTERVALS } ?: "day"
        val trendsFilter = source.optJSONObject("trendsFilter")
        val display = trendsFilter?.stringOrNull("display") ?: query.stringOrNull("display")
        val resolved = response.optJSONObject("resolved_date_range")
        val resolvedFrom = resolved?.stringOrNull("date_from")
        val resolvedTo = resolved?.stringOrNull("date_to")

        val current = entries.filter { compareOf(it) != "previous" }
        val firstPoints = pointsOf(current.firstOrNull())
        val inProgressAt = inProgressFrom(firstPoints, resolvedTo, interval, fetchedAt)
        val format = formatOf(trendsFilter)
        val number = display == "BoldNumber" ||
            (!hasBreakdown(source) && (seriesNodes(source).size == 1 || current.size == 1))
        val parts = if (number) numberParts(source, entries, format, inProgressAt) else null
        // A change against zero has no percent, so it gets no pill, like iOS.
        val delta = parts?.delta?.takeIf { it.points || it.percent != null || it.change == 0.0 }

        return ChartSnapshot(
            pinId = pinId,
            fetchedAt = fetchedAt,
            lastRefreshAt = response.stringOrNull("last_refresh"),
            rangeLabel = rangeLabel(source, resolvedFrom, resolvedTo, interval),
            intervalLabel = interval,
            valueText = parts?.let { formatValue(it.value, format, compact = true) },
            deltaPercent = delta?.let { if (it.points) it.change else it.percent },
            deltaText = delta?.let { deltaText(it) },
            deltaBasis = delta?.let { deltaBasis(it, interval) },
            inProgress = inProgressAt != null,
            series = seriesOf(current, entries),
            chartKind = if (display in BAR_DISPLAYS) "bar" else "line",
        )
    }

    private fun compareOf(entry: JSONObject): String? = when (entry.optString("compare_label")) {
        "previous" -> "previous"
        "current" -> "current"
        else -> null
    }

    private fun seriesIndexOf(entry: JSONObject, fallback: Int): Int =
        (entry.optJSONObject("action")?.opt("order") as? Number)?.toInt() ?: fallback

    private fun breakdownKey(entry: JSONObject): String? =
        entry.opt("breakdown_value")?.takeIf { it != JSONObject.NULL }?.toString()

    private fun breakdownLabel(entry: JSONObject): String? {
        fun part(value: Any?): String? = when (value) {
            BREAKDOWN_OTHER -> "Other"
            BREAKDOWN_NULL -> "None"
            is String -> value
            is Number -> value.toString()
            else -> null
        }
        return when (val value = entry.opt("breakdown_value")) {
            is JSONArray -> (0 until value.length()).mapNotNull { part(value.opt(it)) }.takeIf { it.isNotEmpty() }?.joinToString(", ")
            else -> part(value)
        }
    }

    private fun labelOf(entry: JSONObject, index: Int): String {
        val raw = entry.stringOrNull("label")
            ?.replace(BREAKDOWN_OTHER, "Other")?.replace(BREAKDOWN_NULL, "None")
            ?: "Series ${seriesIndexOf(entry, index) + 1}"
        val breakdown = breakdownLabel(entry)
        return if (breakdown.isNullOrEmpty() || raw.contains(breakdown)) raw else "$raw · $breakdown"
    }

    private fun pointsOf(entry: JSONObject?): List<Point> {
        val days = entry?.optJSONArray("days") ?: return emptyList()
        val data = entry.optJSONArray("data") ?: return emptyList()
        val length = min(days.length(), data.length())
        return (0 until length).map { index ->
            Point(days.optString(index), (data.opt(index) as? Number)?.toDouble()?.takeIf { it.isFinite() } ?: Double.NaN)
        }
    }

    private fun seriesOf(current: List<JSONObject>, entries: List<JSONObject>): List<SnapshotSeries> {
        val shown = current.take(MAX_SERIES)
        val length = pointsOf(shown.firstOrNull()).size
        val start = max(0, length - MAX_POINTS)
        val result = shown.mapIndexed { index, entry ->
            SnapshotSeries(labelOf(entry, index), pointsOf(entry).drop(start).map { SnapshotPoint(it.at, it.value) }, false)
        }.toMutableList()
        val first = shown.firstOrNull()
        if (shown.size == 1 && first != null) {
            val partner = entries.firstOrNull {
                compareOf(it) == "previous" && seriesIndexOf(it, 0) == seriesIndexOf(first, 0) && breakdownKey(it) == breakdownKey(first)
            }
            if (partner != null) {
                val points = pointsOf(partner).take(length).drop(start).map { SnapshotPoint(it.at, it.value) }
                result.add(SnapshotSeries("Previous period", points, true))
            }
        }
        return result
    }

    private fun seriesNodes(source: JSONObject): List<JSONObject> {
        val series = source.optJSONArray("series") ?: return emptyList()
        return (0 until series.length()).mapNotNull { series.optJSONObject(it) }
    }

    private fun hasBreakdown(source: JSONObject): Boolean {
        val filter = source.optJSONObject("breakdownFilter") ?: return false
        val breakdown = filter.opt("breakdown")
        val single = breakdown != null && breakdown != JSONObject.NULL && breakdown != false && breakdown != ""
        return single || (filter.optJSONArray("breakdowns")?.length() ?: 0) > 0
    }

    private fun isSummable(source: JSONObject): Boolean =
        seriesNodes(source).firstOrNull()?.stringOrNull("math") in SUMMABLE_MATH

    private fun inProgressFrom(points: List<Point>, resolvedTo: String?, interval: String, now: Long): String? {
        val last = points.lastOrNull() ?: return null
        if (resolvedTo != null) {
            val to = DateText.parseInstant(resolvedTo) ?: return null
            return if (to > now) last.at else null
        }
        val start = DateText.parseInstant(last.at) ?: return null
        return if (start + (INTERVAL_MS[interval] ?: 0L) > now) last.at else null
    }

    /**
     * The big number and its delta, so both describe the same thing: the server aggregate against the previous
     * aggregate; with a compare series and summable math the window totals; else the last complete bucket against the
     * same bucket of the previous period, or the bucket before it.
     */
    private fun numberParts(source: JSONObject, entries: List<JSONObject>, format: ValueFormat, inProgressAt: String?): NumberParts? {
        val current = entries.firstOrNull { compareOf(it) != "previous" } ?: return null
        val index0 = seriesIndexOf(current, 0)
        val previousEntry = entries.firstOrNull {
            compareOf(it) == "previous" && seriesIndexOf(it, 0) == index0 && breakdownKey(it) == breakdownKey(current)
        }
        val aggregate = current.doubleOrNull("aggregated_value")
        if (aggregate != null) {
            val previousAggregate = previousEntry?.doubleOrNull("aggregated_value")
            return NumberParts(aggregate, previousAggregate?.let { makeDelta(aggregate, it, true, null, format) })
        }
        val points = pointsOf(current)
        val previousPoints = pointsOf(previousEntry)
        if (previousEntry != null && isSummable(source)) {
            val total = sumFinite(points) ?: return null
            val previousTotal = sumFinite(previousPoints)
            return NumberParts(total, previousTotal?.let { makeDelta(total, it, true, null, format) })
        }
        val complete = if (inProgressAt != null && points.lastOrNull()?.at == inProgressAt) points.dropLast(1) else points
        val index = complete.indexOfLast { it.value.isFinite() }
        if (index < 0) return null
        val point = complete[index]
        val against = if (previousEntry != null) previousPoints.getOrNull(index) else complete.getOrNull(index - 1)
        val delta = against?.takeIf { it.value.isFinite() }
            ?.let { makeDelta(point.value, it.value, previousEntry != null, it.at, format) }
        return NumberParts(point.value, delta)
    }

    private fun sumFinite(points: List<Point>): Double? =
        points.map { it.value }.filter { it.isFinite() }.takeIf { it.isNotEmpty() }?.sum()

    private fun makeDelta(value: Double, previous: Double, compare: Boolean, previousAt: String?, format: ValueFormat): Delta {
        val change = value - previous
        val points = format.style == "percentage" || format.style == "percentage_scaled"
        return Delta(
            change = if (format.style == "percentage_scaled") change * 100 else change,
            percent = if (previous == 0.0) null else change / abs(previous) * 100,
            points = points,
            compare = compare,
            previousAt = previousAt,
        )
    }

    private fun deltaText(delta: Delta): String {
        if (delta.change == 0.0) return "No change"
        if (delta.points) return "${number(abs(delta.change), 1, 1)} pts"
        val size = abs(delta.percent ?: 0.0)
        return "${number(size, if (size >= 10) 0 else 1)}%"
    }

    /** `deltaBasisText` in snapshotChart.ts: "vs previous period" or "vs Oct 12". */
    private fun deltaBasis(delta: Delta, interval: String): String {
        val at = delta.previousAt
        if (delta.compare || at == null) return "vs previous period"
        return "vs ${DateText.axisDate(at, interval)}"
    }

    internal fun formatOf(filter: JSONObject?): ValueFormat {
        fun precision(key: String): Int? =
            (filter?.opt(key) as? Number)?.takeIf { it.toDouble() == floor(it.toDouble()) }?.toInt()?.takeIf { it in 0..100 }
        return ValueFormat(
            style = filter?.stringOrNull("aggregationAxisFormat"),
            prefix = filter?.stringOrNull("aggregationAxisPrefix") ?: "",
            suffix = filter?.stringOrNull("aggregationAxisPostfix") ?: "",
            decimalPlaces = precision("decimalPlaces"),
            minDecimalPlaces = precision("minDecimalPlaces"),
        )
    }

    /**
     * `formatInsightValue` for trends. `compact` writes counts and amounts from 10,000 up as "18.3k" or "1.2M", like the
     * pin cards, because a widget has room for few digits.
     */
    internal fun formatValue(value: Double, format: ValueFormat, compact: Boolean): String {
        val style = format.style
        val scaled = if (style == "percentage_scaled") value * 100 else value
        val formatted = when (style) {
            "percentage", "percentage_scaled" ->
                "${number(scaled, format.decimalPlaces ?: significantDecimals(scaled, format.minDecimalPlaces))}%"
            "currency" -> if (compact && abs(value) >= 10_000) "$${compactNumber(value)}" else "$${number(value, 2, 2)}"
            "short" -> shortNumber(value)
            "duration" -> duration(value * 1000)
            "duration_ms" -> duration(value)
            "duration_ns" -> when {
                abs(value) < 1000 -> "${number(value, 2)}ns"
                abs(value) < 1_000_000 -> "${number(value / 1000, 2)}µs"
                else -> duration(value / 1_000_000)
            }
            else -> if (compact && abs(scaled) >= 10_000) {
                compactNumber(scaled)
            } else {
                val minimum = format.minDecimalPlaces ?: 0
                number(scaled, format.decimalPlaces ?: significantDecimals(scaled, format.minDecimalPlaces), minimum)
            }
        }
        val prefix = if (style == "currency" && format.prefix.isNotEmpty() && formatted.startsWith(format.prefix)) "" else format.prefix
        return "$prefix$formatted${format.suffix}"
    }

    /** `toLocaleString('en-US')` with the given fraction digits, rounding half away from zero like ICU. */
    internal fun number(value: Double, maximumFractionDigits: Int, minimumFractionDigits: Int = 0): String {
        val format = DecimalFormat("#,##0", DecimalFormatSymbols(Locale.US))
        format.maximumFractionDigits = max(maximumFractionDigits, minimumFractionDigits)
        format.minimumFractionDigits = minimumFractionDigits
        format.roundingMode = RoundingMode.HALF_UP
        return format.format(value)
    }

    private fun significantDecimals(value: Double, minimum: Int?): Int {
        val floor = minimum ?: 2
        if (!value.isFinite() || value == 0.0) return floor
        return min(max(floor, 1 - floor(log10(abs(value))).toInt()), 10)
    }

    private fun compactNumber(value: Double): String {
        val units = listOf("k", "M", "B", "T")
        var scaled = value / 1000
        var unit = 0
        while (abs(BigDecimal(scaled).setScale(1, RoundingMode.HALF_UP).toDouble()) >= 1000 && unit < units.size - 1) {
            scaled /= 1000
            unit++
        }
        return "${number(scaled, 1)}${units[unit]}"
    }

    private fun shortNumber(value: Double): String {
        val magnitudes = listOf("", "K", "M", "B", "T", "P", "E", "Z", "Y")
        if (!value.isFinite()) return value.toString()
        var rounded = BigDecimal(value).round(MathContext(3)).toDouble()
        var magnitude = 0
        while (abs(rounded) >= 1000 && magnitude < magnitudes.size - 1) {
            magnitude++
            rounded /= 1000
        }
        val text = BigDecimal(rounded).round(MathContext(3)).stripTrailingZeros().toPlainString()
        return if (magnitude > 0) "$text ${magnitudes[magnitude]}" else text
    }

    private fun duration(milliseconds: Double): String {
        val absolute = abs(milliseconds)
        if (absolute == 0.0) return "0s"
        if (absolute < 60_000) {
            val value = if (absolute < 1000) milliseconds else milliseconds / 1000
            val decimals = min(max(0, 2 - floor(log10(abs(value))).toInt()), 4)
            return "${number(value, decimals)}${if (absolute < 1000) "ms" else "s"}"
        }
        val seconds = floor(absolute / 1000).toLong()
        val days = seconds / 86400
        val hours = (seconds % 86400) / 3600
        val minutes = (seconds % 3600) / 60
        val parts = if (days > 0) listOf(days to "d", hours to "h") else listOf(hours to "h", minutes to "m", seconds % 60 to "s")
        val sign = if (milliseconds < 0) "-" else ""
        return sign + parts.filter { it.first != 0L }.joinToString(" ") { "${it.first}${it.second}" }
    }

    private val PRESETS = mapOf(
        ("dStart" to null) to "Today",
        ("-1dStart" to "-1dEnd") to "Yesterday",
        ("-24h" to null) to "Last 24 hours",
        ("-7d" to null) to "Last 7 days",
        ("-30d" to null) to "Last 30 days",
        ("-90d" to null) to "Last 90 days",
        ("wStart" to null) to "This week",
        ("mStart" to null) to "This month",
        ("-1mStart" to "-1mEnd") to "Last month",
        ("yStart" to null) to "This year",
        ("all" to null) to "All time",
        ("-1h" to null) to "Last hour",
        ("-48h" to null) to "Last 48 hours",
        ("-14d" to null) to "Last 14 days",
        ("-180d" to null) to "Last 180 days",
        ("-1wStart" to "-1wEnd") to "Last week",
    )
    private val RELATIVE = Regex("""^-(\d+)([hdwmy])$""")
    private val RELATIVE_NOUNS = mapOf("h" to "hour", "d" to "day", "w" to "week", "m" to "month", "y" to "year")

    /** `rangeLabel` in rangePresets.ts for the saved range; an unknown range falls back to the resolved window. */
    private fun rangeLabel(source: JSONObject, resolvedFrom: String?, resolvedTo: String?, interval: String): String? {
        val range = source.optJSONObject("dateRange") ?: source.optJSONObject("filters")?.optJSONObject("dateRange")
        val dateFrom = range?.stringOrNull("date_from")
        val dateTo = range?.stringOrNull("date_to")
        val resolvedText = if (resolvedFrom != null && resolvedTo != null) {
            if (interval == "hour") DateText.rangeSpan(resolvedFrom, resolvedTo)
            else DateText.rangeSpan(resolvedFrom.take(10), resolvedTo.take(10))
        } else {
            null
        }
        if (dateFrom == null) return resolvedText
        PRESETS[dateFrom to dateTo]?.let { return it }
        val relative = RELATIVE.matchEntire(dateFrom)
        val noun = relative?.groupValues?.get(2)?.let(RELATIVE_NOUNS::get)
        if (relative != null && noun != null && dateTo == null) {
            val amount = relative.groupValues[1].toInt()
            return if (amount == 1) "Last $noun" else "Last $amount ${noun}s"
        }
        if (DateText.wallTime(dateFrom) != null) return DateText.rangeSpan(dateFrom, dateTo ?: dateFrom)
        return resolvedText ?: dateFrom
    }
}

/** Dates as the server writes them: bucket labels and resolved ranges are wall-clock time in the project timezone. */
internal object DateText {
    private val MONTHS = listOf("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    private val WALL = Regex("""^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?""")
    private val ISO = Regex("""^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?\s*(Z|[+-]\d{2}(?::?\d{2})?)?$""")

    class Wall(val year: Int, val month: Int, val day: Int, val time: String?) {
        val monthDay: String get() = "${MONTHS.getOrElse(month - 1) { "" }} $day"
    }

    fun wallTime(value: String): Wall? {
        val m = WALL.find(value) ?: return null
        val (year, month, day, hour, minute) = m.destructured
        return Wall(year.toInt(), month.toInt(), day.toInt(), if (hour.isEmpty()) null else "$hour:$minute")
    }

    /** Epoch ms. Without an offset the text is device-local wall time, like `parseBucketStart`. */
    fun parseInstant(value: String): Long? {
        val m = ISO.matchEntire(value.trim()) ?: return null
        val g = m.groupValues
        val zone = when {
            g[8].isEmpty() -> TimeZone.getDefault()
            g[8] == "Z" -> TimeZone.getTimeZone("UTC")
            else -> {
                val digits = g[8].substring(1).replace(":", "")
                TimeZone.getTimeZone("GMT${g[8][0]}${digits.take(2)}:${digits.drop(2).ifEmpty { "00" }}")
            }
        }
        val calendar = Calendar.getInstance(zone)
        calendar.clear()
        calendar.set(g[1].toInt(), g[2].toInt() - 1, g[3].toInt(), g[4].toIntOrNull() ?: 0, g[5].toIntOrNull() ?: 0, g[6].toIntOrNull() ?: 0)
        val millis = g[7].take(3).padEnd(3, '0').toIntOrNull() ?: 0
        return calendar.timeInMillis + millis
    }

    /** `formatAxisDate`: "14:00" for hours, "Oct 12" for days and weeks, "Oct 2026" for months. */
    fun axisDate(at: String, interval: String): String {
        val wall = wallTime(at) ?: return at
        return when (interval) {
            "hour" -> wall.time ?: "00:00"
            "month" -> "${MONTHS.getOrElse(wall.month - 1) { "" }} ${wall.year}"
            else -> wall.monthDay
        }
    }

    /** `formatRangeSpan` with " to ", the wording the widget uses instead of a dash: "Oct 22 to Nov 4". */
    fun rangeSpan(from: String, to: String, separator: String = " to "): String {
        val a = wallTime(from)
        val b = wallTime(to)
        if (a == null || b == null) return "$from$separator$to"
        if (a.time != null || b.time != null) return "${a.monthDay} ${a.time ?: "00:00"}$separator${b.monthDay} ${b.time ?: "00:00"}"
        if (a.year != b.year) return "${a.monthDay}, ${a.year}$separator${b.monthDay}, ${b.year}"
        if (a.month == b.month && a.day == b.day) return a.monthDay
        if (a.month == b.month) return "${a.monthDay}$separator${b.day}"
        return "${a.monthDay}$separator${b.monthDay}"
    }
}
