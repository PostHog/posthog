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
        .description("Your first chart pin from Views. Touch and hold to change it.")
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge])
    }
}
