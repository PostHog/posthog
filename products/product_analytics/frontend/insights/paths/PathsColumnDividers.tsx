import { useSankeyLayout } from '@posthog/quill-charts'

/** Chart overlay: a divider before each step once the chart is wide enough to scroll, so the eye
 *  keeps its place in a long path. */
export function PathsColumnDividers(): JSX.Element | null {
    const { layout } = useSankeyLayout()
    if (layout.columnCount <= 5) {
        return null
    }
    return (
        <>
            {layout.columnX.slice(1).map((x, i) => (
                <div
                    key={i}
                    className="absolute top-0 h-full w-0.5 bg-border-primary"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ left: x - 20 }}
                />
            ))}
        </>
    )
}
