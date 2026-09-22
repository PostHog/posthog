import { useSankeyLayout } from '@posthog/quill-charts'

const DROPOFF_WIDTH = 30
const DROPOFF_MAX_RADIUS = 25

/** Chart overlay: a fading block to the right of each node for the users who did not continue,
 *  sized to the part of the node no outgoing ribbon covers. First-step nodes and path ends get
 *  none, matching the SVG renderer. */
export function PathsDropoffs(): JSX.Element {
    const { layout } = useSankeyLayout()
    const outflow = new Map<string, number>()
    for (const link of layout.links) {
        outflow.set(link.source.id, (outflow.get(link.source.id) ?? 0) + link.width)
    }
    return (
        <>
            {layout.nodes.map((node) => {
                const continuing = outflow.get(node.id)
                if (node.column === 0 || continuing === undefined) {
                    return null
                }
                const height = node.y1 - node.y0 - continuing
                if (height < 1) {
                    return null
                }
                return (
                    <div
                        key={node.id}
                        className="absolute bg-gradient-to-b from-[var(--paths-dropoff)] to-[var(--color-bg-surface-primary)]"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            left: Math.round(node.x1),
                            top: Math.round(node.y0 + continuing),
                            width: DROPOFF_WIDTH,
                            height,
                            borderTopRightRadius: Math.min(DROPOFF_MAX_RADIUS, height),
                        }}
                    />
                )
            })}
        </>
    )
}
