import SwiftUI
import WidgetKit

/// Values from src/ui/theme.ts, src/ui/tokens.ts and src/ui/chart/palette.ts, so the widget matches the Views tab.
struct ChartColors {
    let surface: Color
    let ink: Color
    let secondary: Color
    let tertiary: Color
    let hairline: Color
    let barNeutral: Color
    let green: Color
    let red: Color
    let orange: Color
    let previous: Color
    let series: [Color]

    func seriesColor(_ index: Int) -> Color {
        series[index % series.count]
    }

    static func of(_ scheme: ColorScheme) -> ChartColors {
        scheme == .dark ? dark : light
    }

    static let light = ChartColors(
        surface: Color(hex: 0xFFFFFF), ink: Color(hex: 0x1F1F1C), secondary: Color(hex: 0x6B6B65),
        tertiary: Color(hex: 0x8A8A84), hairline: Color(hex: 0xE4E4E0), barNeutral: Color(hex: 0xD6D6D1),
        green: Color(hex: 0x1A7F37), red: Color(hex: 0xCF222E), orange: Color(hex: 0xF54E00), previous: Color(hex: 0xA3A39D),
        series: [0x1D4AFF, 0x621DA6, 0x42827E, 0xCE0E74, 0xF14F58].map { Color(hex: $0) }
    )

    static let dark = ChartColors(
        surface: Color(hex: 0x23262E), ink: Color(hex: 0xF4F4F2), secondary: Color(hex: 0xB4B5BA),
        tertiary: Color(hex: 0x8C8E95), hairline: Color(hex: 0x2E3139), barNeutral: Color(hex: 0x5E6068),
        green: Color(hex: 0x3FB950), red: Color(hex: 0xF85149), orange: Color(hex: 0xFF6B35), previous: Color(hex: 0x6F727A),
        series: [0x6B8AFF, 0x7F26D9, 0x3E7A76, 0xBF0D6C, 0xF0474F].map { Color(hex: $0) }
    )
}

private extension Color {
    init(hex: UInt32) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255,
            opacity: 1
        )
    }
}

struct ChartSurface: View {
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        ChartColors.of(colorScheme).surface
    }
}

private enum PointWindow {
    static let compact = 14
    static let large = TrendsParser.pointLimit
}

struct ChartWidgetView: View {
    let entry: ChartEntry

    @Environment(\.widgetFamily) private var family
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        let colors = ChartColors.of(colorScheme)
        Group {
            switch family {
            case .systemSmall:
                SmallChartLayout(slot: entry.content.primary, now: entry.date, colors: colors)
            case .systemLarge, .systemExtraLarge:
                LargeChartLayout(content: entry.content, now: entry.date, colors: colors)
            default:
                MediumChartLayout(content: entry.content, now: entry.date, colors: colors)
            }
        }
        .widgetURL(entry.content.primary.link)
    }
}

private struct SmallChartLayout: View {
    let slot: ChartSlot
    let now: Date
    let colors: ChartColors

    var body: some View {
        if let snapshot = slot.snapshot {
            VStack(alignment: .leading, spacing: 2) {
                PinTitle(text: slot.title, colors: colors)
                if let value = snapshot.valueText {
                    ValueText(text: value, size: 26, colors: colors)
                    HStack(spacing: 4) {
                        DeltaPill(snapshot: snapshot, colors: colors)
                        RangeText(text: snapshot.rangeLabel, colors: colors)
                    }
                } else {
                    RangeText(text: snapshot.rangeLabel, colors: colors)
                }
                PlotArea(snapshot: snapshot, window: PointWindow.compact, kind: .line, style: .sparkline, colors: colors)
                    .padding(.top, 4)
                AgeLabel(dataDate: snapshot.dataDate, now: now, colors: colors)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        } else {
            StateView(slot: slot, colors: colors)
        }
    }
}

private struct MediumChartLayout: View {
    let content: ChartContent
    let now: Date
    let colors: ChartColors

    var body: some View {
        if let snapshot = content.primary.snapshot {
            ChartPanel(
                title: content.primary.title, snapshot: snapshot, window: PointWindow.compact, axisLabels: false,
                dataDate: content.oldestData, now: now, colors: colors
            )
        } else {
            StateView(slot: content.primary, colors: colors)
        }
    }
}

private struct LargeChartLayout: View {
    let content: ChartContent
    let now: Date
    let colors: ChartColors

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let snapshot = content.primary.snapshot {
                ChartPanel(
                    title: content.primary.title, snapshot: snapshot, window: PointWindow.large, axisLabels: true,
                    dataDate: content.oldestData, now: now, colors: colors
                )
            } else {
                StateView(slot: content.primary, colors: colors)
            }
            if !content.extras.isEmpty {
                HStack(spacing: 8) {
                    ForEach(Array(content.extras.enumerated()), id: \.offset) { _, slot in
                        Link(destination: slot.link) {
                            NumberTile(slot: slot, colors: colors)
                        }
                    }
                }
                .frame(height: 104)
                if content.primary.snapshot == nil, let dataDate = content.oldestData {
                    HStack {
                        Spacer(minLength: 0)
                        AgeLabel(dataDate: dataDate, now: now, colors: colors)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

private struct ChartPanel: View {
    let title: String?
    let snapshot: ChartSnapshot
    let window: Int
    let axisLabels: Bool
    let dataDate: Date?
    let now: Date
    let colors: ChartColors

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 5) {
                Image(systemName: snapshot.chartKind == .bar ? "chart.bar.fill" : "chart.xyaxis.line")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(colors.secondary)
                PinTitle(text: title, colors: colors)
            }
            if let value = snapshot.valueText {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    ValueText(text: value, size: 26, colors: colors)
                        .layoutPriority(1)
                    DeltaPill(snapshot: snapshot, colors: colors)
                    if snapshot.pillText != nil, let basis = snapshot.deltaBasis {
                        Text(basis)
                            .font(.system(size: 10.5))
                            .foregroundStyle(colors.secondary)
                            .lineLimit(1)
                    }
                }
            }
            PlotArea(snapshot: snapshot, window: window, kind: snapshot.chartKind, style: .chart, colors: colors)
                .padding(.top, 2)
            if axisLabels, let ends = snapshot.axisLabels(limit: window) {
                HStack {
                    Text(ends.0)
                    Spacer(minLength: 8)
                    Text(ends.1)
                }
                .font(.system(size: 10.5))
                .foregroundStyle(colors.tertiary)
                .lineLimit(1)
            }
            HStack(spacing: 8) {
                RangeText(text: snapshot.rangeLabel, colors: colors)
                Spacer(minLength: 0)
                if let dataDate {
                    AgeLabel(dataDate: dataDate, now: now, colors: colors)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

private struct NumberTile: View {
    let slot: ChartSlot
    let colors: ChartColors

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            PinTitle(text: slot.title, colors: colors)
            switch slot.state {
            case .ready(let snapshot):
                RangeText(text: snapshot.rangeLabel, colors: colors)
                HStack(alignment: .firstTextBaseline, spacing: 4) {
                    ValueText(text: snapshot.valueText ?? "", size: 20, colors: colors)
                    DeltaPill(snapshot: snapshot, colors: colors)
                }
                PlotArea(snapshot: snapshot, window: PointWindow.compact, kind: .line, style: .sparkline, colors: colors)
            case .loading:
                Text("Loading…")
                    .font(.system(size: 12))
                    .foregroundStyle(colors.secondary)
                PlaceholderSparkline(colors: colors)
            case .message(let text, let detail):
                Text(text)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(colors.secondary)
                    .lineLimit(3)
                if let detail {
                    Text(detail)
                        .font(.system(size: 10.5))
                        .foregroundStyle(colors.secondary)
                        .lineLimit(2)
                }
                Spacer(minLength: 0)
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(colors.hairline, lineWidth: 1))
    }
}

private struct StateView: View {
    let slot: ChartSlot
    let colors: ChartColors

    var body: some View {
        VStack(spacing: 4) {
            if let title = slot.title {
                Text(title)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(colors.ink)
                    .lineLimit(1)
            }
            switch slot.state {
            case .message(let text, let detail):
                Text(text)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(colors.secondary)
                if let detail {
                    Text(detail)
                        .font(.system(size: 12))
                        .foregroundStyle(colors.secondary)
                }
            case .loading:
                Text("Loading…")
                    .font(.system(size: 12))
                    .foregroundStyle(colors.secondary)
                PlaceholderSparkline(colors: colors)
                    .frame(maxWidth: 120, maxHeight: 28)
                    .padding(.top, 4)
            case .ready:
                EmptyView()
            }
        }
        .multilineTextAlignment(.center)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct PinTitle: View {
    let text: String?
    let colors: ChartColors

    var body: some View {
        Text(text ?? "")
            .font(.system(size: 12, weight: .semibold))
            .foregroundStyle(colors.ink)
            .lineLimit(1)
    }
}

private struct ValueText: View {
    let text: String
    let size: CGFloat
    let colors: ChartColors

    var body: some View {
        Text(text)
            .font(.system(size: size, weight: .bold))
            .monospacedDigit()
            .foregroundStyle(colors.ink)
            .lineLimit(1)
            .minimumScaleFactor(0.5)
    }
}

private struct RangeText: View {
    let text: String?
    let colors: ChartColors

    var body: some View {
        if let text {
            Text(text)
                .font(.system(size: 10.5))
                .foregroundStyle(colors.secondary)
                .lineLimit(1)
        }
    }
}

private struct AgeLabel: View {
    let dataDate: Date
    let now: Date
    let colors: ChartColors

    var body: some View {
        Text(ChartAge.text(dataDate: dataDate, at: now))
            .font(.system(size: 10.5))
            .foregroundStyle(ChartAge.isStale(dataDate: dataDate, at: now) ? colors.orange : colors.tertiary)
            .lineLimit(1)
    }
}

private struct DeltaPill: View {
    let snapshot: ChartSnapshot
    let colors: ChartColors

    var body: some View {
        if let text = snapshot.pillText {
            let direction = snapshot.deltaPercent ?? 0
            let tint = direction > 0 ? colors.green : direction < 0 ? colors.red : colors.secondary
            Text(text)
                .font(.system(size: 10.5, weight: .semibold))
                .monospacedDigit()
                .foregroundStyle(tint)
                .lineLimit(1)
                .fixedSize()
                .padding(.horizontal, 5)
                .padding(.vertical, 1.5)
                .background(tint.opacity(0.12), in: Capsule())
        }
    }
}

private enum PlotStyle {
    /// Floats above the floor, so a flat-ish series reads as a line (src/ui/chart/Sparkline.tsx).
    case sparkline
    /// Axis scaling with three grid lines (`yAxisTicks` in src/ui/chart/chartMath.ts).
    case chart
}

private struct PlotArea: View {
    let snapshot: ChartSnapshot
    let window: Int
    let kind: ChartKind
    let style: PlotStyle
    let colors: ChartColors

    var body: some View {
        if snapshot.hasPoints {
            Plot(series: snapshot.trimmed(to: window), kind: kind, style: style, colors: colors)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .accessibilityHidden(true)
        } else {
            Text("No data for this range")
                .font(.system(size: 10.5))
                .foregroundStyle(colors.tertiary)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}

private struct PlaceholderSparkline: View {
    let colors: ChartColors

    private static let wave: [ChartSeries] = [
        ChartSeries(
            label: "",
            points: [0.5, 0.62, 0.55, 0.7, 0.64, 0.78, 0.7, 0.84, 0.76, 0.9].enumerated().map {
                ChartPoint(at: String($0.offset), value: $0.element)
            },
            previous: false
        ),
    ]

    var body: some View {
        Plot(series: Self.wave, kind: .line, style: .sparkline, colors: colors, tint: colors.hairline, fillsArea: false)
            .accessibilityHidden(true)
    }
}

private struct Plot: View {
    let series: [ChartSeries]
    let kind: ChartKind
    let style: PlotStyle
    let colors: ChartColors
    var tint: Color? = nil
    var fillsArea = true

    private var current: [ChartSeries] { series.filter { !$0.previous } }
    private var previous: [ChartSeries] { kind == .line && style == .chart ? series.filter(\.previous) : [] }

    var body: some View {
        GeometryReader { proxy in
            let scale = PlotScale(series: current + previous, kind: kind, style: style, size: proxy.size)
            ZStack {
                if style == .chart {
                    scale.gridPath().stroke(colors.hairline, lineWidth: 1)
                }
                if kind == .bar && style == .chart {
                    bars(scale)
                } else {
                    lines(scale)
                }
            }
        }
    }

    @ViewBuilder
    private func lines(_ scale: PlotScale) -> some View {
        if fillsArea, current.count == 1, let only = current.first {
            scale.areaPath(only.points).fill(
                LinearGradient(
                    colors: [colors.seriesColor(0).opacity(0.18), colors.seriesColor(0).opacity(0.02)],
                    startPoint: .top, endPoint: .bottom
                )
            )
        }
        ForEach(Array(previous.enumerated()), id: \.offset) { _, line in
            scale.linePath(line.points)
                .stroke(colors.previous, style: StrokeStyle(lineWidth: 1.5, lineCap: .round, lineJoin: .round, dash: [3, 3]))
        }
        ForEach(Array(current.enumerated()), id: \.offset) { index, line in
            scale.linePath(line.points)
                .stroke(tint ?? colors.seriesColor(index), style: StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))
        }
    }

    @ViewBuilder
    private func bars(_ scale: PlotScale) -> some View {
        if current.count == 1, let only = current.first {
            let last = only.points.count - 1
            scale.barsPath(only.points, series: 0, of: 1) { $0 != last }.fill(colors.barNeutral)
            scale.barsPath(only.points, series: 0, of: 1) { $0 == last }.fill(colors.ink)
        } else {
            ForEach(Array(current.enumerated()), id: \.offset) { index, bar in
                scale.barsPath(bar.points, series: index, of: current.count) { _ in true }.fill(colors.seriesColor(index))
            }
        }
    }
}

private struct PlotScale {
    let size: CGSize
    let count: Int
    let low: Double
    let high: Double
    /// Room above and below, so a 2pt stroke at the extremes is not clipped.
    let inset: CGFloat = 2

    init(series: [ChartSeries], kind: ChartKind, style: PlotStyle, size: CGSize) {
        self.size = size
        count = series.first { !$0.previous }?.points.count ?? 0
        let values = series.flatMap { $0.points.compactMap(\.value) }
        (low, high) = Self.domain(values, kind: kind, style: style)
    }

    private static func domain(_ values: [Double], kind: ChartKind, style: PlotStyle) -> (Double, Double) {
        guard let minimum = values.min(), let maximum = values.max() else { return (0, 1) }
        let span = maximum - minimum
        var low: Double
        var high: Double
        switch (style, kind) {
        case (.sparkline, _):
            low = minimum >= 0 ? max(0, minimum - span * 0.6) : minimum - span * 0.6
            high = maximum + span * 0.1
        case (.chart, .bar):
            low = min(0, minimum)
            high = max(0, maximum)
        case (.chart, .line):
            let pad = span > 0 ? span * 0.05 : (abs(maximum) * 0.1 == 0 ? 1 : abs(maximum) * 0.1)
            low = minimum - pad
            high = maximum + pad
            if minimum >= 0 && low < 0 {
                low = 0
            }
        }
        if high <= low {
            // A flat series sits in the middle.
            low -= 1
            high += 1
        }
        return (low, high)
    }

    func x(_ index: Int) -> CGFloat {
        count <= 1 ? size.width / 2 : CGFloat(index) / CGFloat(count - 1) * size.width
    }

    func y(_ value: Double) -> CGFloat {
        let fraction = (value - low) / (high - low)
        return inset + (1 - CGFloat(fraction)) * max(0, size.height - inset * 2)
    }

    func gridPath() -> Path {
        var path = Path()
        for fraction in [0.0, 0.5, 1.0] {
            let y = inset + CGFloat(fraction) * max(0, size.height - inset * 2)
            path.move(to: CGPoint(x: 0, y: y))
            path.addLine(to: CGPoint(x: size.width, y: y))
        }
        return path
    }

    func linePath(_ points: [ChartPoint]) -> Path {
        var path = Path()
        var pen = false
        for (index, point) in points.enumerated() {
            guard let value = point.value else {
                pen = false
                continue
            }
            let location = CGPoint(x: x(index), y: y(value))
            if pen {
                path.addLine(to: location)
            } else {
                path.move(to: location)
            }
            pen = true
        }
        return path
    }

    func areaPath(_ points: [ChartPoint]) -> Path {
        let drawn = points.enumerated().compactMap { index, point in point.value.map { CGPoint(x: x(index), y: y($0)) } }
        guard let first = drawn.first, let last = drawn.last, drawn.count > 1 else { return Path() }
        var path = Path()
        path.move(to: first)
        drawn.dropFirst().forEach { path.addLine(to: $0) }
        path.addLine(to: CGPoint(x: last.x, y: size.height))
        path.addLine(to: CGPoint(x: first.x, y: size.height))
        path.closeSubpath()
        return path
    }

    func barsPath(_ points: [ChartPoint], series: Int, of seriesCount: Int, including: (Int) -> Bool) -> Path {
        guard count > 0 else { return Path() }
        let slot = size.width / CGFloat(count)
        let group = slot * 0.72
        let width = group / CGFloat(max(1, seriesCount))
        let gap = seriesCount > 1 ? min(1, width * 0.2) : 0
        let baseline = y(min(max(0, low), high))
        var path = Path()
        for (index, point) in points.enumerated() where including(index) {
            guard let value = point.value else { continue }
            let top = y(value)
            let rect = CGRect(
                x: slot * CGFloat(index) + (slot - group) / 2 + width * CGFloat(series),
                y: min(top, baseline),
                width: max(0.5, width - gap),
                height: max(0.5, abs(baseline - top))
            )
            path.addRoundedRect(in: rect, cornerSize: CGSize(width: min(2, rect.width / 2), height: min(2, rect.height / 2)))
        }
        return path
    }
}
