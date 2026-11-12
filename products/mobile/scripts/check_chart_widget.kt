package com.posthog.code.mobile.chart

import org.json.JSONArray
import org.json.JSONObject
import java.io.File

fun main(args: Array<String>) {
    val fixtures = JSONArray(File(args.single()).readText())
    for (index in 0 until fixtures.length()) {
        val fixture = fixtures.getJSONObject(index)
        val expected = fixture.getJSONObject("expected")
        val pin = CatalogPin("pin-example", "insight", "Example", "", 101, "example1", null, true, true, true, null)
        val snapshot = InsightParser.parse(fixture.getJSONObject("response"), pin, 1793617200000L)
        val name = fixture.getString("name")
        for ((field, actual) in listOf("chartValueText" to snapshot.chartValueText, "axisLowText" to snapshot.axisLowText, "axisHighText" to snapshot.axisHighText)) {
            if (expected.has(field)) check(actual == expected.stringOrNull(field)) { "$name: $field" }
        }
        if (expected.has("intervalLabel")) check(snapshot.intervalLabel == expected.getString("intervalLabel")) { "$name: interval" }
        check(snapshot.display == expected.getString("display")) { "$name: display ${snapshot.display}" }
        if (expected.has("valueText")) check(snapshot.valueText == expected.stringOrNull("valueText")) { "$name: value ${snapshot.valueText}" }
        if (expected.has("firstAt")) check(snapshot.series.first().points.first().at == expected.getString("firstAt")) { "$name: date" }
        if (expected.has("firstValue")) check(snapshot.series.first().points.first().value == expected.getDouble("firstValue")) { "$name: duplicate sum" }
        if (expected.optBoolean("lastIsGap")) check(snapshot.series.first().points.last().value.isNaN()) { "$name: gap" }
        if (expected.has("firstRowValue")) check(snapshot.rows.first().value == expected.getString("firstRowValue")) { "$name: first row" }
        if (expected.has("rowCount")) check(snapshot.rows.size == expected.getInt("rowCount")) { "$name: rows" }
        if (expected.has("seriesCount")) check(snapshot.series.size == expected.getInt("seriesCount")) { "$name: series" }
        if (expected.has("lastValue")) check(snapshot.series.first().points.last().value == expected.getDouble("lastValue")) { "$name: last value" }
        check(ChartSnapshot.parse(snapshot.toJson()) == snapshot) { "$name: round trip" }
        println("ok $name")
    }
    check(InsightParser.number("1".repeat(16000) + "!") == null)
    check(InsightParser.number(" -1.25e2 ") == -125.0)
    val rows = JSONArray()
    val start = java.time.LocalDateTime.of(2026, 1, 1, 0, 0)
    for (index in 0 until 10_000) {
        val at = start.plusHours(index.toLong()).toString()
        rows.put(JSONArray(listOf(at, 1)))
        rows.put(JSONArray(listOf(at, 2)))
    }
    val response = JSONObject().put("query", JSONObject().put("kind", "DataVisualizationNode")
        .put("source", JSONObject().put("kind", "HogQLQuery")).put("display", "ActionsLineGraphCumulative"))
        .put("columns", JSONArray(listOf("at", "value")))
        .put("types", JSONArray().put(JSONArray(listOf("at", "DateTime"))).put(JSONArray(listOf("value", "UInt64"))))
        .put("result", rows)
    val pin = CatalogPin("scale", "insight", "Example", "", 101, "example1", null, true, true, true, null)
    val snapshot = InsightParser.parse(response, pin, 1793617200000L)
    check(snapshot.series.single().points.size == 60)
    check(snapshot.series.single().points.first().value == 29_823.0)
    check(snapshot.series.single().points.last().value == 30_000.0)
    println("ok large cumulative SQL result")

}
