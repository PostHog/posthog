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
        .description("A hedgehog that wanders around your home screen. Tap it to say hi.")
        .supportedFamilies([.systemSmall, .systemMedium])
        .contentMarginsDisabled()
    }
}
