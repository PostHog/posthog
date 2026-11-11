import SwiftUI
import WidgetKit

struct HedgehogWidget: Widget {
    let kind = "HedgehogWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: HedgehogTimelineProvider()) { entry in
            HedgehogView(entry: entry)
                .containerBackground(for: .widget) {
                    GeometryReader { geometry in
                        Image("hoglet_garden")
                            .resizable()
                            .scaledToFill()
                            .frame(width: geometry.size.width, height: geometry.size.height)
                            .clipped()
                    }
                }
        }
        .configurationDisplayName("Hedgehog")
        .description("Your own little garden hedgehog. Tap to change its character.")
        .supportedFamilies([.systemSmall, .systemMedium])
        .contentMarginsDisabled()
    }
}
