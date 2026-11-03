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

            Button(intent: PokeHedgehogIntent(family: String(describing: family))) {
                sprite
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Hedgehog")
            .accessibilityHint("Tap to change hedgehog")
            // Each bounce is applied inside the hop before it, so its own delayed animation wins for its rotation.
            .modifier(HopLayer(hop: entry.hop(2), spin: 0, radius: radius, spriteSize: spriteSize, date: entry.date, reduceMotion: reduceMotion))
            .modifier(HopLayer(hop: entry.hop(1), spin: 0, radius: radius, spriteSize: spriteSize, date: entry.date, reduceMotion: reduceMotion))
            .modifier(HopLayer(hop: entry.hop(0), spin: entry.spin, radius: radius, spriteSize: spriteSize, date: entry.date, reduceMotion: reduceMotion))
            // Button content changes must not override the position animation.
            .geometryGroup()
            .position(x: feetX(width: geometry.size.width), y: floorY - spriteSize / 2)
            .animation(travelAnimation, value: entry.tick.x)
        }
    }

    private var sprite: some View {
        (hoggieImage.map { Image(uiImage: $0) } ?? Image(spriteName))
            .interpolation(illustrated ? .high : .none)
            .resizable()
            .frame(width: spriteSize, height: spriteSize)
            .contentShape(Rectangle())
            .scaleEffect(x: entry.tick.facing == .left ? -1 : 1, y: 1)
            .contentTransition(.identity)
            .animation(nil, value: entry.tick.facing)
    }

    /// An entry holds one image for its whole beat. Without the hop the airborne pose would read as floating.
    private var spriteName: String {
        guard reduceMotion, entry.airborne else { return entry.tick.spriteName }
        return Tick(pose: .jump, frame: 9, x: entry.tick.x, y: 0, facing: entry.tick.facing).spriteName
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

/// A full turn about a point above the sprite moves it up and back down to the same spot; the counter-turn keeps it upright.
private struct HopLayer: ViewModifier {
    let hop: Hop
    let spin: Double
    let radius: CGFloat
    let spriteSize: CGFloat
    let date: Date
    let reduceMotion: Bool

    func body(content: Content) -> some View {
        let degrees = reduceMotion ? 0 : hop.degrees
        let spin = reduceMotion ? 0 : spin
        content
            // Both rotations end on whole turns, so a delayed timeline update leaves the hog on its feet.
            .rotationEffect(.degrees(spin - degrees))
            .rotationEffect(.degrees(degrees), anchor: UnitPoint(x: 0.5, y: 0.5 - radius * hop.apex / spriteSize))
            // Every entry has a new date. An entry that does not hop on this layer gets no animation, so its turns go
            // back to zero at once, which looks the same as a whole turn.
            .animation(animation, value: date)
    }

    private var animation: Animation? {
        guard !reduceMotion, hop.duration > 0 else { return nil }
        return .linear(duration: hop.duration).delay(hop.delay)
    }
}
