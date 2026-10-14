import SwiftUI
import WidgetKit

/// Colors from src/ui/tokens.ts, so the widget matches the app.
enum Palette {
    static let background = Color(hex: 0xF6F6F3)
    static let ground = Color(hex: 0xF0F0ED)
    static let floorLine = Color(hex: 0xD6D6D1)
    static let bubbleFill = Color(hex: 0xFFFFFF)
    static let bubbleBorder = Color(hex: 0xE4E4E0)
    static let ink = Color(hex: 0x1F1F1C)
}

private extension Color {
    init(hex: UInt32) {
        self.init(
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255
        )
    }
}

struct HedgehogView: View {
    let entry: HedgehogEntry

    @Environment(\.widgetFamily) private var family
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    // In the square 160px cell the opaque body spans x 28...130 and y 36...156. The cell's bottom edge
    // sits on the floor line, and these fractions keep the body (not the empty cell) inside the widget.
    private static let artTopInset: CGFloat = 36 / 160
    private static let artHalfWidth: CGFloat = 51 / 160
    // The middle of the body, so a flip turns around the hedgehog and not around the empty corner of the cell.
    private static let spinAnchor = UnitPoint(x: 79.0 / 160, y: 96.0 / 160)
    private static let bubbleFont = Font.system(size: 12, weight: .semibold)

    private var spriteSize: CGFloat { family == .systemSmall ? 56 : 64 }
    private var floorInset: CGFloat { family == .systemSmall ? 18 : 20 }
    private var edgePadding: CGFloat { 8 }

    var body: some View {
        GeometryReader { geometry in
            let size = geometry.size
            let floorY = size.height - floorInset
            let feetX = feetX(width: size.width)
            let lift = lift(floorY: floorY)

            ZStack(alignment: .topLeading) {
                Palette.ground
                    .frame(width: size.width, height: floorInset)
                    .offset(y: floorY)
                Palette.floorLine
                    .frame(width: size.width, height: 1)
                    .offset(y: floorY)

                // Each move has its own animation, so a jump travels at an even speed while it rises fast and
                // falls faster. The innermost animation wins for the values it watches.
                // Only the hedgehog is a button. A tap anywhere else falls through to the widget, which opens the app.
                Button(intent: PokeHedgehogIntent(family: String(describing: family))) {
                    sprite
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Hedgehog")
                .rotationEffect(.degrees(reduceMotion ? 0 : entry.spin), anchor: Self.spinAnchor)
                .animation(spinAnimation, value: entry.spin)
                .offset(y: floorY - spriteSize - lift)
                .animation(liftAnimation, value: lift)
                .offset(x: feetX - spriteSize / 2)
                .animation(travelAnimation, value: feetX)

                ZStack {
                    if let bubble = entry.tick.bubble, !bubble.isEmpty {
                        bubbleView(bubble)
                            .position(bubblePosition(for: bubble, feetX: feetX, feetY: floorY - lift, width: size.width))
                            .transition(.scale(scale: 0.6, anchor: .bottom).combined(with: .opacity))
                    }
                }
                .animation(reduceMotion ? nil : .spring(duration: 0.4, bounce: 0.4), value: entry.tick.bubble)
                .animation(travelAnimation, value: feetX)
                // The bubble overlaps the empty top of the sprite cell and must not block a poke there.
                .allowsHitTesting(false)
            }
            .frame(width: size.width, height: size.height, alignment: .topLeading)
        }
    }

    private var sprite: some View {
        Image(entry.tick.spriteName)
            .interpolation(.none)
            .resizable()
            .frame(width: spriteSize, height: spriteSize)
            .contentShape(Rectangle())
            .scaleEffect(x: entry.tick.facing == .left ? -1 : 1, y: 1)
            .animation(reduceMotion ? nil : .spring(duration: 0.35, bounce: 0.2), value: entry.tick.facing)
    }

    private var travelAnimation: Animation? {
        guard !reduceMotion else { return nil }
        switch entry.motion {
        case .settle:
            return .spring(duration: 0.6, bounce: 0.3)
        case let .glide(duration), let .rise(duration), let .drop(duration):
            return .linear(duration: duration)
        }
    }

    private var liftAnimation: Animation? {
        guard !reduceMotion else { return nil }
        switch entry.motion {
        case let .rise(duration):
            return .easeOut(duration: duration)
        case let .drop(duration):
            return .easeIn(duration: duration)
        case .settle, .glide:
            return .spring(duration: 0.5, bounce: 0.3)
        }
    }

    /// A tick without a turn resets the angle from a whole turn to zero, which must not animate backwards.
    private var spinAnimation: Animation? {
        (entry.tick.turn ?? 0) != 0 ? liftAnimation : nil
    }

    private func bubbleView(_ text: String) -> some View {
        Text(text)
            .font(Self.bubbleFont)
            .foregroundStyle(Palette.ink)
            .lineLimit(1)
            .fixedSize()
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(Capsule().fill(Palette.bubbleFill))
            .overlay(Capsule().strokeBorder(Palette.bubbleBorder, lineWidth: 1))
    }

    private func feetX(width: CGFloat) -> CGFloat {
        let margin = spriteSize * Self.artHalfWidth + edgePadding
        return margin + clamp(entry.tick.x) * max(width - 2 * margin, 0)
    }

    private func lift(floorY: CGFloat) -> CGFloat {
        let artHeight = spriteSize * (1 - Self.artTopInset)
        let rise = max(floorY - artHeight - edgePadding, 0)
        return clamp(entry.tick.y) * rise
    }

    /// The bubble width is estimated because its laid-out size is not known when it is positioned.
    private func bubblePosition(for text: String, feetX: CGFloat, feetY: CGFloat, width: CGFloat) -> CGPoint {
        let estimatedHalfWidth = (CGFloat(text.count) * 6.6 + 16) / 2
        let minX = estimatedHalfWidth + 4
        let maxX = width - estimatedHalfWidth - 4
        let x = minX <= maxX ? min(max(feetX, minX), maxX) : width / 2
        let headY = feetY - spriteSize * (1 - Self.artTopInset)
        return CGPoint(x: x, y: max(headY - 12, 14))
    }

    private func clamp(_ value: Double) -> CGFloat {
        CGFloat(min(max(value, 0), 1))
    }
}
