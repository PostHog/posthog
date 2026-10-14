import SwiftUI
import UIKit
import WidgetKit

struct HedgehogView: View {
    let entry: HedgehogEntry

    @Environment(\.widgetFamily) private var family
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var hoggieImage: UIImage? { entry.tick.hoggie.flatMap { UIImage(named: "hoggie_\($0)") } }
    private var illustrated: Bool { hoggieImage != nil }
    private var illustratedSize: CGFloat { family == .systemSmall ? 92 : 106 }
    private var spriteSize: CGFloat { illustrated ? illustratedSize : (family == .systemSmall ? 68 : 78) }
    // Keep the travel envelope fixed when a tap changes the artwork size.
    private var travelMargin: CGFloat { illustratedSize / 2 + hopRadius + edgePadding }
    private var floorInset: CGFloat { family == .systemSmall ? 18 : 20 }
    private var edgePadding: CGFloat { 8 }
    private var hopRadius: CGFloat { illustratedSize * 0.16 }

    var body: some View {
        GeometryReader { geometry in
            let floorY = geometry.size.height - floorInset
            let radius = max(0, min(hopRadius, (floorY - illustratedSize - edgePadding) / 2))
            let orbit = reduceMotion ? 0 : (entry.orbit ?? 0)
            let spin = reduceMotion ? 0 : entry.spin

            Button(intent: PokeHedgehogIntent(family: String(describing: family))) {
                sprite
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Hedgehog")
            .accessibilityHint("Tap to change hedgehog")
            // Both rotations end on whole turns, so a delayed timeline update leaves the hog on its feet.
            .rotationEffect(.degrees(spin - orbit))
            .rotationEffect(.degrees(orbit), anchor: UnitPoint(x: 0.5, y: 0.5 - radius / spriteSize))
            .animation(travelAnimation, value: orbit)
            .offset(x: feetX(width: geometry.size.width) - spriteSize / 2, y: floorY - spriteSize)
            .animation(travelAnimation, value: entry.tick.x)
            .frame(width: geometry.size.width, height: geometry.size.height, alignment: .topLeading)
        }
    }

    private var sprite: some View {
        (hoggieImage.map { Image(uiImage: $0) } ?? Image(entry.tick.spriteName))
            .interpolation(illustrated ? .high : .none)
            .resizable()
            .frame(width: spriteSize, height: spriteSize)
            .contentShape(Rectangle())
            .scaleEffect(x: entry.tick.facing == .left ? -1 : 1, y: 1)
            .contentTransition(.identity)
            .animation(nil, value: entry.tick.facing)
            .animation(nil, value: entry.tick.spriteName)
            .animation(nil, value: entry.tick.hoggie)
    }

    private var travelAnimation: Animation? {
        guard !reduceMotion else { return nil }
        switch entry.motion {
        case .settle:
            return .easeInOut(duration: 0.6)
        case let .glide(duration), let .rise(duration), let .drop(duration):
            return .linear(duration: duration)
        }
    }

    private func feetX(width: CGFloat) -> CGFloat {
        let margin = min(travelMargin, width / 2)
        return margin + clamp(entry.tick.x) * max(width - 2 * margin, 0)
    }

    private func clamp(_ value: Double) -> CGFloat {
        CGFloat(min(max(value, 0), 1))
    }
}
