import { useRadialLayout } from '@posthog/quill-charts'

const MIN_FONT_SIZE = 12
const MAX_FONT_SIZE = 64
/** Share of the hole's diameter the total is allowed to span. */
const HOLE_FILL = 0.7
/** Measured advance width of a bold digit in the app font, as a share of the font size. */
const CHAR_WIDTH_EM = 0.55

export function DonutCenterLabel({ children }: { children: string }): JSX.Element {
    const { layout } = useRadialLayout()

    // Fit the total to the ring's hole, which grows and shrinks with the chart, so the number reads
    // the same on a dashboard card as on a full insight.
    const available = layout.innerRadius * 2 * HOLE_FILL
    const fontSize = Math.round(
        Math.min(MAX_FONT_SIZE, Math.max(MIN_FONT_SIZE, available / (Math.max(children.length, 1) * CHAR_WIDTH_EM)))
    )

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div className="text-center font-bold leading-none" style={{ fontSize }}>
            {children}
        </div>
    )
}
