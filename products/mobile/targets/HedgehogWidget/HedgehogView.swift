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
    private static let bubbleFont = Font.system(size: 12, weight: .semibold)

    private var spriteSize: CGFloat { family == .systemSmall ? 56 : 64 }
    private var floorInset: CGFloat { family == .systemSmall ? 18 : 20 }
    private var edgePadding: CGFloat { 8 }

    var body: some View {
        GeometryReader { geometry in
            let size = geometry.size
            let floorY = size.height - floorInset
            let feet = feetPosition(in: size, floorY: floorY)

            ZStack(alignment: .topLeading) {
                Palette.ground
                    .frame(width: size.width, height: floorInset)
                    .offset(y: floorY)
                Palette.floorLine
                    .frame(width: size.width, height: 1)
                    .offset(y: floorY)

                Group {
                    sprite
                        .position(x: feet.x, y: feet.y - spriteSize / 2)
                    if let bubble = entry.tick.bubble, !bubble.isEmpty {
                        bubbleView(bubble)
                            .position(bubblePosition(for: bubble, feet: feet, width: size.width))
                            .transition(.scale.combined(with: .opacity))
                    }
                }
                .animation(reduceMotion ? nil : .spring(duration: 0.9, bounce: 0.3), value: entry.tick)

                // The button covers the whole widget, so a tap anywhere pokes the hedgehog and the tap target
                // does not move with the sprite.
                Button(intent: PokeHedgehogIntent(family: String(describing: family))) {
                    Color.clear.contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Hedgehog")
            }
            .frame(width: size.width, height: size.height, alignment: .topLeading)
        }
    }

    private var sprite: some View {
        Image(entry.tick.spriteName)
            .interpolation(.none)
            .resizable()
            .frame(width: spriteSize, height: spriteSize)
            .scaleEffect(x: entry.tick.facing == .left ? -1 : 1, y: 1)
            .accessibilityHidden(true)
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

    private func feetPosition(in size: CGSize, floorY: CGFloat) -> CGPoint {
        let tick = entry.tick
        let margin = spriteSize * Self.artHalfWidth + edgePadding
        let x = margin + clamp(tick.x) * max(size.width - 2 * margin, 0)
        let artHeight = spriteSize * (1 - Self.artTopInset)
        let rise = max(floorY - artHeight - edgePadding, 0)
        return CGPoint(x: x, y: floorY - clamp(tick.y) * rise)
    }

    /// The bubble width is estimated because its laid-out size is not known when it is positioned.
    private func bubblePosition(for text: String, feet: CGPoint, width: CGFloat) -> CGPoint {
        let estimatedHalfWidth = (CGFloat(text.count) * 6.6 + 16) / 2
        let minX = estimatedHalfWidth + 4
        let maxX = width - estimatedHalfWidth - 4
        let x = minX <= maxX ? min(max(feet.x, minX), maxX) : width / 2
        let headY = feet.y - spriteSize * (1 - Self.artTopInset)
        return CGPoint(x: x, y: max(headY - 12, 14))
    }

    private func clamp(_ value: Double) -> CGFloat {
        CGFloat(min(max(value, 0), 1))
    }
}
