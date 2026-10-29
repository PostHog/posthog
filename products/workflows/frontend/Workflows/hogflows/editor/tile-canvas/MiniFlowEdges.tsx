import type { MiniFlowLayout } from './tileCanvasModel'

const STROKE = { fill: 'none', stroke: 'var(--border-bold)', strokeWidth: 1.25 }

export function MiniFlowEdges({ layout, opacity }: { layout: MiniFlowLayout; opacity: number }): JSX.Element {
    return (
        <svg className="absolute inset-0 overflow-visible" width={layout.width} height={layout.height}>
            {layout.edges.map(({ from, to }, index) => {
                const midX = (from.x + to.x) / 2
                return (
                    <g
                        key={index}
                        className="transition-opacity duration-200 motion-reduce:transition-none"
                        style={{ opacity }}
                    >
                        <path d={`M ${from.x} ${from.y} H ${midX} V ${to.y} H ${to.x - 1}`} {...STROKE} />
                        <path
                            d={`M ${to.x - 5} ${to.y - 3} L ${to.x - 1} ${to.y} L ${to.x - 5} ${to.y + 3}`}
                            {...STROKE}
                        />
                    </g>
                )
            })}
        </svg>
    )
}
