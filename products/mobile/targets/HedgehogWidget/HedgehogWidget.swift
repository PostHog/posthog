import SwiftUI
import WidgetKit

struct HedgehogWidget: Widget {
    let kind = "HedgehogWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: HedgehogTimelineProvider()) { entry in
            HedgehogView(entry: entry)
                .containerBackground(for: .widget) {
                    Palette.background
                }
        }
        .configurationDisplayName("Hedgehog")
        .description("A roaming hedgehog with visiting hoggies. Tap one for a surprise.")
        .supportedFamilies([.systemSmall, .systemMedium])
        .contentMarginsDisabled()
    }
}
