package com.posthog.code.mobile.chart

import org.json.JSONArray
import org.json.JSONObject

/** Matches the result shapes consumed by the Views adapters, without running app JavaScript in a widget. */
object InsightParser {
    fun parse(response: JSONObject, pin: CatalogPin, now: Long): ChartSnapshot {
        val query = response.optJSONObject("query") ?: JSONObject()
        val source = query.optJSONObject("source") ?: query
        val kind = source.optString("kind")
        if (kind == "TrendsQuery") {
            val snapshot = chartLabels(TrendsParser.parse(response, pin.id, now)) { value ->
                val filter = source.optJSONObject("trendsFilter")
                TrendsParser.formatValue(value, TrendsParser.formatOf(filter), false)
            }
            if (pin.displayMode == "number" && pin.number) return snapshot.copy(display = "number")
            val filter = source.optJSONObject("trendsFilter")
            val display = filter?.stringOrNull("display") ?: query.stringOrNull("display")
            if (display in setOf("ActionsPie", "ActionsTable", "WorldMap", "ActionsBarValue", "ActionsDonut", "ActionsProportionBar")) {
                val format = TrendsParser.ValueFormat(filter?.stringOrNull("aggregationAxisFormat"),
                    filter?.optString("aggregationAxisPrefix") ?: "", filter?.optString("aggregationAxisPostfix") ?: "", null, null)
                val rows = objects(response.optJSONArray("result")).filter { it.optString("compare_label") != "previous" && number(it.opt("aggregated_value")) != null }
                    .sortedWith(compareBy<JSONObject> { it.optString("breakdown_value") == "\$\$_posthog_breakdown_other_\$\$" }.thenByDescending { number(it.opt("aggregated_value")) })
                    .take(12).map { entry ->
                    val value = number(entry.opt("aggregated_value"))
                    SnapshotRow(entry.optString("label", "Value"), value?.let { TrendsParser.formatValue(it, format, false) } ?: "–")
                }
                return snapshot.copy(display = "rows", rows = rows)
            }
            return snapshot.copy(display = if (pin.displayMode == "number" || display == "BoldNumber") "number" else "chart")
        }
        val base = ChartSnapshot(pin.id, now, response.stringOrNull("last_refresh"), null, "day", null,
            null, null, null, false, emptyList(), "line", "rows")
        if (kind == "HogQLQuery") return sql(response, query, base)
        val result = response.optJSONArray("result")
        if (kind == "FunnelsQuery" && result != null) {
            val groups = if (result.opt(0) is JSONArray) values(result).mapNotNull { it as? JSONArray }.map(::objects) else listOf(objects(result))
            val first = groups.firstOrNull() ?: emptyList()
            val layout = source.optJSONObject("funnelsFilter")?.stringOrNull("funnelVizType")
            if ((layout != null && layout != "steps") || first.any { number(it.opt("count")) == null }) return base.copy(rows = genericRows(result))
            val counts = first.indices.map { i -> groups.sumOf { number(it.getOrNull(i)?.opt("count")) ?: 0.0 } }
            if (source.optJSONObject("breakdownFilter")?.optString("breakdown_type") == "cohort" && groups.size > 1) {
                return base.copy(rows = genericRows(result))
            }
            val rows = first.mapIndexed { i, step -> SnapshotRow(step.stringOrNull("custom_name") ?: step.optString("name", "Step ${i + 1}"), text(counts[i])) }.take(12)
            val entered = counts.firstOrNull() ?: 0.0
            return base.copy(rows = rows, valueText = if (counts.size > 1 && entered > 0) "${TrendsParser.number(counts.last() / entered * 100, 1)}%" else null,
                rangeLabel = "Overall conversion")
        }
        if (kind == "RetentionQuery" && result != null) {
            val filter = source.optJSONObject("retentionFilter")
            val records = objects(result)
            val aggregation = filter?.stringOrNull("aggregationType")
            val breakdown = source.optJSONObject("breakdownFilter")
            if ((aggregation != null && aggregation != "count") || breakdown?.stringOrNull("breakdown") != null ||
                (breakdown?.optJSONArray("breakdowns")?.length() ?: 0) > 0 || records.any { !it.isNull("breakdown_value") }) {
                return base.copy(rows = genericRows(result))
            }
            val period = filter?.optString("period", "Day") ?: "Day"
            val previous = filter?.optString("retentionReference") == "previous"
            val rows = records.take(12).mapNotNull { row ->
                val start = row.stringOrNull("date")?.let { DateText.parseInstant(it) } ?: return@mapNotNull null
                val counts = objects(row.optJSONArray("values")).map { number(it.opt("count")) ?: 0.0 }
                val calendar = java.util.Calendar.getInstance(java.util.TimeZone.getTimeZone("UTC"))
                calendar.timeInMillis = start
                val available = counts.indices.takeWhile { i ->
                    calendar.timeInMillis = start
                    when (period) {
                        "Month" -> calendar.add(java.util.Calendar.MONTH, i)
                        "Week" -> calendar.add(java.util.Calendar.DAY_OF_YEAR, 7 * i)
                        "Hour" -> calendar.add(java.util.Calendar.HOUR_OF_DAY, i)
                        else -> calendar.add(java.util.Calendar.DAY_OF_YEAR, i)
                    }
                    calendar.timeInMillis <= now
                }
                val percentages = available.map { i ->
                    val count = counts[i]
                    val denominator = if (previous && i > 0) counts[i - 1] else counts.firstOrNull() ?: 0.0
                    "${TrendsParser.number(if (denominator > 0) count / denominator * 100 else 0.0, 0)}%"
                }
                SnapshotRow(row.optString("date", "Cohort").take(10), percentages.joinToString(" · "))
            }
            return base.copy(rows = rows, rangeLabel = "${filter?.optString("period", "Day") ?: "Day"} retention")
        }
        return base.copy(rows = genericRows(response.opt("result")))
    }

    private fun chartLabels(snapshot: ChartSnapshot, format: (Double) -> String): ChartSnapshot {
        val current = snapshot.series.filter { !it.previous }
        val values = snapshot.series.filter { snapshot.chartKind != "bar" || !it.previous }.flatMap { it.points.map { p -> p.value } }.filter { it.isFinite() }
        return snapshot.copy(
            chartValueText = current.singleOrNull()?.points?.lastOrNull { it.value.isFinite() }?.let { format(it.value) },
            axisLowText = values.minOrNull()?.let { format(if (snapshot.chartKind == "bar") minOf(0.0, it) else it) },
            axisHighText = values.maxOrNull()?.let { format(if (snapshot.chartKind == "bar") maxOf(0.0, it) else it) },
        )
    }

    internal fun number(value: Any?): Double? = when (value) {
        is Number -> value.toDouble().takeIf { it.isFinite() }
        is String -> value.takeIf { it.length <= 128 && it.matches(Regex("\\s*[-+]?(?:[0-9]+(?:\\.[0-9]*)?|\\.[0-9]+)(?:[eE][-+]?[0-9]+)?\\s*")) }?.toDoubleOrNull()?.takeIf { it.isFinite() }
        else -> null
    }

    private fun values(array: JSONArray?): List<Any?> = if (array == null) emptyList() else (0 until array.length()).map { array.opt(it) }
    private fun objects(array: JSONArray?): List<JSONObject> = values(array).mapNotNull { it as? JSONObject }
    private fun text(value: Any?): String = when {
        value == null || value == JSONObject.NULL -> "–"
        value is String -> value
        value is JSONArray -> values(value).take(6).joinToString(" · ") { text(it) }
        number(value) != null -> TrendsParser.number(number(value)!!, 3)
        else -> value.toString()
    }

    private fun genericRows(value: Any?): List<SnapshotRow> {
        if (value is JSONArray) return values(value).take(12).flatMapIndexed { index, row ->
            if (row is JSONObject) {
                val label = row.stringOrNull("label") ?: row.stringOrNull("name") ?: row.stringOrNull("date") ?: "Row ${index + 1}"
                val key = listOf("count", "aggregated_value", "value", "data").firstOrNull { row.has(it) }
                if (key != null) listOf(SnapshotRow(label, text(row.opt(key))))
                else row.keys().asSequence().sorted().take(6).map { SnapshotRow(it, text(row.opt(it))) }.toList()
            } else listOf(SnapshotRow("Value ${index + 1}", text(row)))
        }
        if (value is JSONObject) return value.keys().asSequence().sorted().take(12).map { SnapshotRow(it, text(value.opt(it))) }.toList()
        return if (value == null || value == JSONObject.NULL) emptyList() else listOf(SnapshotRow("Value", text(value)))
    }

    private fun formatting(query: JSONObject, column: String, display: String = "chart"): JSONObject {
        val table = objects(query.optJSONObject("tableSettings")?.optJSONArray("columns"))
        val axes = objects(query.optJSONObject("chartSettings")?.optJSONArray("yAxis"))
        fun format(entries: List<JSONObject>): JSONObject? = entries.firstOrNull { it.optString("column") == column }?.optJSONObject("settings")?.optJSONObject("formatting")
        return (when (display) { "number" -> format(table); "table" -> format(table) ?: format(axes); else -> format(axes) ?: format(table) }) ?: JSONObject()
    }

    private fun sqlText(cell: Any?, format: JSONObject): String {
        val value = number(cell) ?: return text(cell)
        val style = format.stringOrNull("style")
        val digits = (format.opt("decimalPlaces") as? Number)?.toInt()?.coerceIn(0, 100)
        val scaled = if (style == "percent") value * 100 else value
        val formatted = when (style) {
            "short" -> TrendsParser.formatValue(value, TrendsParser.ValueFormat("short", "", "", null, null), false)
            "number", "percent" -> TrendsParser.number(scaled, digits ?: 3, digits ?: 0) + if (style == "percent") "%" else ""
            else -> if (digits != null) String.format(java.util.Locale.US, "%.${digits}f", scaled) else java.math.BigDecimal.valueOf(scaled).stripTrailingZeros().toPlainString()
        }
        return format.optString("prefix", "") + formatted + format.optString("suffix", "")
    }

    private fun sqlDate(value: Any?): String? {
        val match = (value as? String)?.trim()?.let { Regex("""^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2})(:\d{2})?(?:\.\d+)?)?(?:Z|[+-]\d{2}(?::?\d{2})?)?$""").matchEntire(it) } ?: return null
        val (date, time, seconds) = match.destructured
        val at = if (time.isEmpty()) date else "$date $time${seconds.ifEmpty { ":00" }}"
        return at.takeIf { DateText.parseInstant(it) != null }
    }

    private fun sqlInterval(dates: List<String>): String {
        val times = dates.mapNotNull { DateText.parseInstant(it) }.distinct().sorted()
        val gaps = times.zipWithNext { a, b -> b - a }.sorted()
        val median = gaps.getOrNull(gaps.size / 2) ?: return "day"
        return when {
            median < 21 * 3_600_000L -> "hour"
            median < 6 * 86_400_000L -> "day"
            median < 28 * 86_400_000L -> "week"
            else -> "month"
        }
    }

    private fun sql(response: JSONObject, query: JSONObject, base: ChartSnapshot): ChartSnapshot {
        val rows = values(response.optJSONArray("result")).mapNotNull { it as? JSONArray }
        val columns = values(response.optJSONArray("columns")).map { it.toString() }
        val types = values(response.optJSONArray("types")).map { (it as? JSONArray)?.optString(1) ?: "" }
        fun scalar(index: Int): String {
            var type = types.getOrNull(index)?.trim() ?: ""
            while ((type.startsWith("Nullable(") || type.startsWith("LowCardinality(")) && type.endsWith(")")) {
                type = type.substringAfter('(').dropLast(1).trim()
            }
            return type
        }
        fun date(index: Int): Boolean = scalar(index).startsWith("Date")
        fun numeric(index: Int): Boolean = listOf("Int", "UInt", "Float", "Decimal").any { scalar(index).startsWith(it) }
        val settings = query.optJSONObject("chartSettings") ?: JSONObject()
        val savedX = settings.optJSONObject("xAxis")?.stringOrNull("column")
        val x = columns.indexOf(savedX).takeIf { it >= 0 } ?: columns.indices.firstOrNull(::date) ?: columns.indices.firstOrNull { !numeric(it) }
        val namedY = objects(settings.optJSONArray("yAxis")).mapNotNull { columns.indexOf(it.optString("column")).takeIf { i -> i >= 0 } }
        val breakdown = columns.indexOf(settings.stringOrNull("seriesBreakdownColumn")).takeIf { it >= 0 }
        val y = (namedY.ifEmpty { columns.indices.filter(::numeric) }).filter { it != x && it != breakdown }
        var display = query.optString("display", "ActionsTable")
        if (display == "Auto") display = when {
            columns.size == 1 && numeric(0) -> "BoldNumber"
            x != null && date(x) && y.isNotEmpty() && rows.size > 1 -> "ActionsLineGraph"
            else -> "ActionsTable"
        }
        if (display == "BoldNumber") return base.copy(display = "number", valueText = rows.firstOrNull()?.takeIf { !it.isNull(0) }?.let { sqlText(it.opt(0), formatting(query, columns.firstOrNull() ?: "", "number")) })
        val overTime = display in setOf("ActionsLineGraph", "ActionsLineGraphCumulative", "ActionsAreaGraph", "ActionsBar", "ActionsStackedBar", "ActionsUnstackedBar")
        if (overTime && x != null && date(x) && y.isNotEmpty()) {
            val dates = sortedSetOf<String>()
            val sums = linkedMapOf<String, MutableMap<Int, MutableMap<String, Double>>>()
            for (row in rows) {
                val at = sqlDate(row.opt(x)) ?: continue
                dates.add(at)
                val group = breakdown?.let { text(row.opt(it)) } ?: ""
                if (!sums.containsKey(group) && sums.size >= 5) continue
                val byColumn = sums.getOrPut(group) { mutableMapOf() }
                for (column in y.take(5)) {
                    val value = number(row.opt(column)) ?: continue
                    val byDate = byColumn.getOrPut(column) { mutableMapOf() }
                    byDate[at] = (byDate[at] ?: 0.0) + value
                }
            }
            val axis = dates.toList()
            val visibleDates = axis.takeLast(60)
            val series = y.asSequence().flatMap { column -> sums.keys.asSequence().map { group ->
                val byDate = sums[group]?.get(column).orEmpty()
                var total = if (display == "ActionsLineGraphCumulative") axis.dropLast(visibleDates.size).sumOf { byDate[it] ?: 0.0 } else 0.0
                val points = visibleDates.map { at ->
                    var value = byDate[at]
                    if (display == "ActionsLineGraphCumulative" && value != null) { total += value; value = total }
                    SnapshotPoint(at, value ?: Double.NaN)
                }
                SnapshotSeries(if (group.isEmpty()) columns[column] else "${columns[column]} · $group", points, false)
            } }.take(5).toList()
            val snapshot = base.copy(display = "chart", intervalLabel = sqlInterval(dates.toList()), series = series, chartKind = if (display.contains("Bar") || objects(settings.optJSONArray("yAxis")).firstOrNull()?.optJSONObject("settings")?.optJSONObject("display")?.optString("displayType") == "bar") "bar" else "line")
            return chartLabels(snapshot) { sqlText(it, formatting(query, columns[y[0]])) }
        }
        return base.copy(rows = rows.take(12).map { row ->
            val label = x?.let { text(row.opt(it)) } ?: "Value"
            val indices = columns.indices.filter { it != x }
            SnapshotRow(label, indices.joinToString(" · ") { if (numeric(it)) sqlText(row.opt(it), formatting(query, columns[it], "table")) else text(row.opt(it)) })
        })
    }
}
