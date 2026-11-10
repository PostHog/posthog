import CoreFoundation
import Foundation

/// Uses the same result shapes as the Views adapters; the widget never evaluates a query itself.
enum InsightParser {
  static func snapshot(response: JSONObject, pin: ChartPin, now: Date) throws -> ChartSnapshot {
    let query = response["query"] as? JSONObject ?? [:]
    let source = query["source"] as? JSONObject ?? query
    let kind = source["kind"] as? String
    if kind == "TrendsQuery" {
      var snapshot = try TrendsParser.snapshot(response: response, pinId: pin.id, now: now)
      chartLabels(&snapshot) {
        TrendsParser.formatValue($0, TrendsParser.valueFormat(source: source))
      }
      let display = TrendsParser.displayOf(query)
      if pin.displayMode == "number" && pin.number {
        snapshot.display = "number"
        return snapshot
      }
      if [
        "ActionsPie", "ActionsTable", "WorldMap", "ActionsBarValue", "ActionsDonut",
        "ActionsProportionBar",
      ].contains(display) {
        let entries = response["result"] as? [JSONObject] ?? []
        let format = TrendsParser.valueFormat(source: source)
        snapshot.rows = entries.filter {
          $0["compare_label"] as? String != "previous" && number($0["aggregated_value"]) != nil
        }.sorted {
          let leftOther = $0["breakdown_value"] as? String == "$$_posthog_breakdown_other_$$"
          let rightOther = $1["breakdown_value"] as? String == "$$_posthog_breakdown_other_$$"
          return leftOther != rightOther
            ? !leftOther
            : (number($0["aggregated_value"]) ?? 0) > (number($1["aggregated_value"]) ?? 0)
        }.prefix(12).map { entry in
          let value = number(entry["aggregated_value"])
          return ChartRow(
            label: entry["label"] as? String ?? "Value",
            value: value.map { TrendsParser.formatValue($0, format) } ?? "–")
        }
        snapshot.display = "rows"
      } else {
        snapshot.display =
          pin.displayMode == "number" || display == "BoldNumber" ? "number" : "chart"
      }
      return snapshot
    }
    var snapshot = ChartSnapshot(
      version: 1, pinId: pin.id, fetchedAt: now.timeIntervalSince1970 * 1000,
      lastRefreshAt: response["last_refresh"] as? String, rangeLabel: nil, intervalLabel: "day",
      valueText: nil, deltaPercent: nil, deltaText: nil, deltaBasis: nil, series: [],
      chartKind: .line,
      display: "rows", rows: []
    )
    if kind == "HogQLQuery" {
      sql(response: response, query: query, snapshot: &snapshot)
    } else if kind == "FunnelsQuery", let result = response["result"] as? [Any] {
      let groups =
        result.first is [Any]
        ? result.compactMap { $0 as? [JSONObject] } : [result.compactMap { $0 as? JSONObject }]
      let first = groups.first ?? []
      let layout = (source["funnelsFilter"] as? JSONObject)?["funnelVizType"] as? String
      if (layout != nil && layout != "steps")
        || first.contains(where: { number($0["count"]) == nil })
      {
        snapshot.rows = genericRows(result)
        return snapshot
      }
      let counts = first.indices.map { index in
        groups.reduce(0.0) { $0 + (index < $1.count ? number($1[index]["count"]) ?? 0 : 0) }
      }
      snapshot.rows = first.enumerated().prefix(12).map { index, step in
        ChartRow(
          label: step["custom_name"] as? String ?? step["name"] as? String ?? "Step \(index + 1)",
          value: text(counts[index]))
      }
      // Cohort breakdowns can overlap, so their counts must never be added together.
      let breakdown = source["breakdownFilter"] as? JSONObject
      if breakdown?["breakdown_type"] as? String == "cohort", groups.count > 1 {
        snapshot.rows = genericRows(result)
      } else if let entered = counts.first, let converted = counts.last, counts.count > 1,
        entered > 0
      {
        snapshot.valueText = "\(TrendsParser.number(converted / entered * 100, maxDigits: 1))%"
        snapshot.rangeLabel = "Overall conversion"
      }
    } else if kind == "RetentionQuery", let result = response["result"] as? [JSONObject] {
      let filter = source["retentionFilter"] as? JSONObject ?? [:]
      let aggregation = filter["aggregationType"] as? String
      let breakdown = source["breakdownFilter"] as? JSONObject ?? [:]
      if (aggregation != nil && aggregation != "count") || breakdown["breakdown"] is String
        || !(breakdown["breakdowns"] as? [Any] ?? []).isEmpty
        || result.contains(where: {
          $0["breakdown_value"] != nil && !($0["breakdown_value"] is NSNull)
        })
      {
        snapshot.rows = genericRows(result)
        return snapshot
      }
      let period = filter["period"] as? String ?? "Day"
      let previous = filter["retentionReference"] as? String == "previous"
      snapshot.rows = result.prefix(12).compactMap { row in
        guard let date = row["date"] as? String, let start = ChartDates.parse(date) else {
          return nil
        }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        let cells = row["values"] as? [JSONObject] ?? []
        let counts = cells.map { number($0["count"]) ?? 0 }
        let available = counts.indices.prefix { index in
          let component: Calendar.Component =
            period == "Month" ? .month : period == "Hour" ? .hour : .day
          let amount = period == "Week" ? index * 7 : index
          return calendar.date(byAdding: component, value: amount, to: start).map { $0 <= now }
            ?? false
        }
        let values = available.map { index in
          let count = counts[index]
          let base = previous && index > 0 ? counts[index - 1] : counts.first ?? 0
          return "\(TrendsParser.number(base > 0 ? count / base * 100 : 0, maxDigits: 0))%"
        }
        return ChartRow(
          label: String((row["date"] as? String ?? "Cohort").prefix(10)),
          value: values.joined(separator: " · "))
      }
      snapshot.rangeLabel = "\(filter["period"] as? String ?? "Day") retention"
    } else {
      snapshot.rows = genericRows(response["result"])
    }
    return snapshot
  }

  private static func chartLabels(_ snapshot: inout ChartSnapshot, format: (Double) -> String) {
    let current = snapshot.series.filter { !$0.previous }
    let values = snapshot.series.filter { snapshot.chartKind != .bar || !$0.previous }.flatMap {
      $0.points.compactMap(\.value)
    }
    if current.count == 1, let value = current[0].points.last(where: { $0.value != nil })?.value {
      snapshot.chartValueText = format(value)
    }
    if let low = values.min(), let high = values.max() {
      snapshot.axisLowText = format(snapshot.chartKind == .bar ? min(0, low) : low)
      snapshot.axisHighText = format(snapshot.chartKind == .bar ? max(0, high) : high)
    }
  }

  static func number(_ value: Any?) -> Double? {
    if let value = value as? NSNumber, CFGetTypeID(value) != CFBooleanGetTypeID() {
      return value.doubleValue.isFinite ? value.doubleValue : nil
    }
    if let value = value as? String, value.utf8.count <= 128,
      value.range(
        of: "^\\s*[-+]?(?:[0-9]+(?:\\.[0-9]*)?|\\.[0-9]+)(?:[eE][-+]?[0-9]+)?\\s*$",
        options: .regularExpression) != nil,
      let parsed = Double(value.trimmingCharacters(in: .whitespacesAndNewlines)), parsed.isFinite
    {
      return parsed
    }
    return nil
  }

  private static func text(_ value: Any?) -> String {
    guard let value, !(value is NSNull) else { return "–" }
    if let value = value as? String { return value }
    if let value = value as? NSNumber, CFGetTypeID(value) == CFBooleanGetTypeID() {
      return value.boolValue ? "true" : "false"
    }
    if let value = number(value) { return TrendsParser.number(value, maxDigits: 3) }
    if let list = value as? [Any] {
      return list.prefix(6).map { text($0) }.joined(separator: " · ")
    }
    return String(describing: value)
  }

  private static func genericRows(_ result: Any?) -> [ChartRow] {
    if let rows = result as? [Any] {
      return rows.prefix(12).enumerated().flatMap { index, row -> [ChartRow] in
        if let row = row as? JSONObject {
          let label =
            row["label"] as? String ?? row["name"] as? String ?? row["date"] as? String
            ?? "Row \(index + 1)"
          if let value = row["count"] ?? row["aggregated_value"] ?? row["value"] ?? row["data"] {
            return [ChartRow(label: label, value: text(value))]
          }
          return row.keys.sorted().prefix(6).map { ChartRow(label: $0, value: text(row[$0])) }
        }
        if let row = row as? [Any] {
          return [ChartRow(label: "Row \(index + 1)", value: text(row))]
        }
        return [ChartRow(label: "Value \(index + 1)", value: text(row))]
      }
    }
    if let result = result as? JSONObject {
      return result.keys.sorted().prefix(12).map { ChartRow(label: $0, value: text(result[$0])) }
    }
    return result == nil ? [] : [ChartRow(label: "Value", value: text(result))]
  }

  private static func formatting(_ query: JSONObject, column: String, display: String)
    -> JSONObject
  {
    let table = (query["tableSettings"] as? JSONObject)?["columns"] as? [JSONObject] ?? []
    let axes = (query["chartSettings"] as? JSONObject)?["yAxis"] as? [JSONObject] ?? []
    func format(_ entries: [JSONObject]) -> JSONObject? {
      let settings = entries.first { $0["column"] as? String == column }?["settings"] as? JSONObject
      return settings?["formatting"] as? JSONObject
    }
    switch display {
    case "number": return format(table) ?? [:]
    case "table": return format(table) ?? format(axes) ?? [:]
    default: return format(axes) ?? format(table) ?? [:]
    }
  }

  private static func sqlText(_ cell: Any?, format: JSONObject) -> String {
    guard let value = number(cell) else { return text(cell) }
    let style = format["style"] as? String
    let digits = (format["decimalPlaces"] as? Int).map { min(100, max(0, $0)) }
    let scaled = style == "percent" ? value * 100 : value
    let formatted: String
    if style == "short" {
      formatted = TrendsParser.formatValue(value, TrendsParser.ValueFormat(style: "short"))
    } else if style == "number" || style == "percent" {
      formatted =
        TrendsParser.number(scaled, maxDigits: digits ?? 3, minDigits: digits ?? 0)
        + (style == "percent" ? "%" : "")
    } else if let digits {
      formatted = String(format: "%.*f", digits, scaled)
    } else {
      formatted =
        value.rounded() == value && abs(value) < 1e16
        ? String(format: "%.0f", value) : String(value)
    }
    return "\(format["prefix"] as? String ?? "")\(formatted)\(format["suffix"] as? String ?? "")"
  }

  private static func sqlDate(_ value: Any) -> String? {
    guard let value = value as? String,
      let regex = try? NSRegularExpression(
        pattern:
          "^(\\d{4}-\\d{2}-\\d{2})(?:[T ](\\d{2}:\\d{2})(:\\d{2})?(?:\\.\\d+)?)?(?:Z|[+-]\\d{2}(?::?\\d{2})?)?$"
      ),
      let match = regex.firstMatch(
        in: value.trimmingCharacters(in: .whitespacesAndNewlines),
        range: NSRange(
          value.trimmingCharacters(in: .whitespacesAndNewlines).startIndex...,
          in: value.trimmingCharacters(in: .whitespacesAndNewlines)))
    else { return nil }
    let text = value.trimmingCharacters(in: .whitespacesAndNewlines) as NSString
    let date = text.substring(with: match.range(at: 1))
    let at =
      match.range(at: 2).location == NSNotFound
      ? date
      : date + " " + text.substring(with: match.range(at: 2))
        + (match.range(at: 3).location == NSNotFound
          ? ":00" : text.substring(with: match.range(at: 3)))
    return ChartDates.parse(at) == nil ? nil : at
  }

  private static func sqlInterval(_ dates: [String]) -> String {
    let times = Array(Set(dates.compactMap { ChartDates.parse($0)?.timeIntervalSince1970 }))
      .sorted()
    let gaps = zip(times, times.dropFirst()).map { $1 - $0 }.sorted()
    guard !gaps.isEmpty else { return "day" }
    let median = gaps[gaps.count / 2]
    if median < 21 * 3600 { return "hour" }
    if median < 6 * 86400 { return "day" }
    return median < 28 * 86400 ? "week" : "month"
  }

  private static func sql(response: JSONObject, query: JSONObject, snapshot: inout ChartSnapshot) {
    let rows = response["result"] as? [[Any]] ?? []
    let columns = response["columns"] as? [String] ?? []
    let types = response["types"] as? [[Any]] ?? []
    let settings = query["chartSettings"] as? JSONObject ?? [:]
    func type(_ index: Int) -> String {
      index < types.count && types[index].count > 1 ? types[index][1] as? String ?? "" : ""
    }
    func scalar(_ index: Int) -> String {
      var value = type(index).trimmingCharacters(in: .whitespaces)
      while value.hasPrefix("Nullable(") || value.hasPrefix("LowCardinality("),
        value.hasSuffix(")"),
        let open = value.firstIndex(of: "(")
      {
        value = String(value[value.index(after: open)...].dropLast()).trimmingCharacters(
          in: .whitespaces)
      }
      return value
    }
    func date(_ index: Int) -> Bool { scalar(index).hasPrefix("Date") }
    func numeric(_ index: Int) -> Bool {
      ["Int", "UInt", "Float", "Decimal"].contains { scalar(index).hasPrefix($0) }
    }
    let ySettings = settings["yAxis"] as? [JSONObject] ?? []
    let savedX = (settings["xAxis"] as? JSONObject)?["column"] as? String
    let x =
      savedX.flatMap { columns.firstIndex(of: $0) } ?? columns.indices.first(where: date)
      ?? columns.indices.first { !numeric($0) }
    let namedY = ySettings.compactMap { entry in
      (entry["column"] as? String).flatMap { columns.firstIndex(of: $0) }
    }
    let breakdownName = settings["seriesBreakdownColumn"] as? String
    let breakdown = breakdownName.flatMap { columns.firstIndex(of: $0) }
    let y = (namedY.isEmpty ? columns.indices.filter(numeric) : namedY).filter {
      $0 != x && $0 != breakdown
    }
    var display = query["display"] as? String ?? "ActionsTable"
    if display == "Auto" {
      display =
        columns.count == 1 && numeric(0)
        ? "BoldNumber"
        : x.map(date) == true && !y.isEmpty && rows.count > 1 ? "ActionsLineGraph" : "ActionsTable"
    }
    if display == "BoldNumber" {
      snapshot.valueText = rows.first?.first.flatMap {
        $0 is NSNull
          ? nil
          : sqlText($0, format: formatting(query, column: columns.first ?? "", display: "number"))
      }
      snapshot.display = "number"
      return
    }
    let overTime = [
      "ActionsLineGraph", "ActionsLineGraphCumulative", "ActionsAreaGraph", "ActionsBar",
      "ActionsStackedBar", "ActionsUnstackedBar",
    ].contains(display)
    if overTime, let x, date(x), !y.isEmpty {
      var dates = Set<String>()
      var groups: [String] = []
      var sums: [String: [Int: [String: Double]]] = [:]
      for row in rows {
        guard row.count > x, let at = sqlDate(row[x]) else { continue }
        dates.insert(at)
        let group = breakdown.map { $0 < row.count ? text(row[$0]) : "–" } ?? ""
        if sums[group] == nil {
          guard groups.count < 5 else { continue }
          groups.append(group)
          sums[group] = [:]
        }
        for column in y.prefix(5) {
          guard column < row.count, let value = number(row[column]) else { continue }
          sums[group, default: [:]][column, default: [:]][at, default: 0] += value
        }
      }
      let axis = dates.sorted()
      snapshot.intervalLabel = sqlInterval(axis)
      let visibleDates = axis.suffix(60)
      snapshot.series = y.prefix(5).flatMap { column in groups.map { (column, $0) } }.prefix(5).map
      {
        column, group -> ChartSeries in
        let byDate = sums[group]?[column] ?? [:]
        var total =
          display == "ActionsLineGraphCumulative"
          ? axis.dropLast(visibleDates.count).reduce(0.0) { $0 + (byDate[$1] ?? 0) } : 0.0
        return ChartSeries(
          label: group.isEmpty ? columns[column] : "\(columns[column]) · \(group)",
          points: visibleDates.map { at in
            var value = byDate[at]
            if display == "ActionsLineGraphCumulative", let v = value {
              total += v
              value = total
            }
            return ChartPoint(at: at, value: value)
          }, previous: false)
      }
      snapshot.display = "chart"
      snapshot.chartKind =
        display.contains("Bar")
          || ((ySettings.first?["settings"] as? JSONObject)?["display"] as? JSONObject)?[
            "displayType"] as? String == "bar"
        ? .bar : .line
      chartLabels(&snapshot) {
        sqlText($0, format: formatting(query, column: columns[y[0]], display: "chart"))
      }
      snapshot.rows = []
      return
    }
    snapshot.rows = rows.prefix(12).map { row in
      let label = x.flatMap { $0 < row.count ? text(row[$0]) : nil } ?? "Value"
      let values = columns.indices.filter { $0 != x }.map { index in
        let cell = index < row.count ? row[index] : nil
        return numeric(index)
          ? sqlText(cell, format: formatting(query, column: columns[index], display: "table"))
          : text(cell)
      }
      return ChartRow(label: label, value: values.joined(separator: " · "))
    }
  }
}
