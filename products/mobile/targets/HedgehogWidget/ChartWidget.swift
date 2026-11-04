import SwiftUI
import WidgetKit

struct ChartWidget: Widget {
    let kind = "ChartWidget"

    var body: some WidgetConfiguration {
        AppIntentConfiguration(kind: kind, intent: ChartWidgetIntent.self, provider: ChartTimelineProvider()) { entry in
            ChartWidgetView(entry: entry)
                .containerBackground(for: .widget) {
                    ChartSurface()
                }
        }
        .configurationDisplayName("Chart")
        .description("A pinned insight from your Views tab, with its latest value.")
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge])
    }
}
