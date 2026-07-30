import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { ScatterPoint, mcpClusteringLogic } from './mcpClusteringLogic'

const WIDTH = 640
const HEIGHT = 280
const PAD = { top: 16, right: 16, bottom: 36, left: 44 }

function scale(value: number, domain: [number, number], range: [number, number]): number {
    const [d0, d1] = domain
    const [r0, r1] = range
    if (d1 === d0) {
        return (r0 + r1) / 2
    }
    return r0 + ((value - d0) / (d1 - d0)) * (r1 - r0)
}

function radius(callCount: number, maxCalls: number): number {
    if (maxCalls <= 0) {
        return 5
    }
    return 4 + 10 * Math.sqrt(callCount / maxCalls)
}

/**
 * Discovery rate vs description fit, one bubble per tool, sized by call volume.
 * The quadrant lines sit at the medians of the plotted tools. The bottom-right
 * quadrant (fits the intent, rarely picked) is where description work pays off
 * most; the top-left (picked despite a poor fit) usually means the description
 * undersells what the tool does.
 */
export function DiscoveryScatter(): JSX.Element | null {
    const { scatterPoints, tools, fitMedian, discoveryMedian } = useValues(mcpClusteringLogic)

    if (scatterPoints.length === 0) {
        return (
            <div className="bg-surface-primary border rounded p-4 text-sm text-muted">
                <span className="font-medium text-default">Discovery vs description fit</span>
                <p className="mt-1 mb-0">
                    This chart needs tools with both a captured description and enough advertised sessions to measure
                    discovery. Descriptions accumulate as new calls are captured; check back after a few days of
                    traffic.
                </p>
            </div>
        )
    }

    const fits = scatterPoints.map((p) => p.fit)
    const fitDomain: [number, number] = [Math.min(...fits, 0), Math.max(...fits, 0.01)]
    const maxCalls = Math.max(...scatterPoints.map((p) => p.callCount))
    const plotX: [number, number] = [PAD.left, WIDTH - PAD.right]
    const plotY: [number, number] = [HEIGHT - PAD.bottom, PAD.top]
    const unplotted = tools.length - scatterPoints.length

    return (
        <div className="bg-surface-primary border rounded p-4 flex flex-col gap-2">
            <div className="flex flex-col">
                <span className="text-xs uppercase text-muted font-medium">Discovery vs description fit</span>
                <span className="text-xs text-muted">
                    Tools in the lower right fit their intents but rarely get picked when advertised: the strongest
                    candidates for a description rewrite.
                </span>
            </div>
            <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full max-w-[720px]" role="img">
                <line
                    x1={PAD.left}
                    y1={HEIGHT - PAD.bottom}
                    x2={WIDTH - PAD.right}
                    y2={HEIGHT - PAD.bottom}
                    stroke="var(--border-primary)"
                />
                <line
                    x1={PAD.left}
                    y1={PAD.top}
                    x2={PAD.left}
                    y2={HEIGHT - PAD.bottom}
                    stroke="var(--border-primary)"
                />
                {fitMedian !== null ? (
                    <line
                        x1={scale(fitMedian, fitDomain, plotX)}
                        y1={PAD.top}
                        x2={scale(fitMedian, fitDomain, plotX)}
                        y2={HEIGHT - PAD.bottom}
                        stroke="var(--border-primary)"
                        strokeDasharray="4 4"
                    />
                ) : null}
                {discoveryMedian !== null ? (
                    <line
                        x1={PAD.left}
                        y1={scale(discoveryMedian, [0, 100], plotY)}
                        x2={WIDTH - PAD.right}
                        y2={scale(discoveryMedian, [0, 100], plotY)}
                        stroke="var(--border-primary)"
                        strokeDasharray="4 4"
                    />
                ) : null}
                <text
                    x={(PAD.left + WIDTH - PAD.right) / 2}
                    y={HEIGHT - 8}
                    textAnchor="middle"
                    className="fill-current text-muted"
                    fontSize={10}
                >
                    Description fit (cosine similarity to served intents)
                </text>
                <text
                    x={12}
                    y={(PAD.top + HEIGHT - PAD.bottom) / 2}
                    textAnchor="middle"
                    transform={`rotate(-90 12 ${(PAD.top + HEIGHT - PAD.bottom) / 2})`}
                    className="fill-current text-muted"
                    fontSize={10}
                >
                    Discovery rate %
                </text>
                {scatterPoints.map((point: ScatterPoint) => (
                    <Tooltip
                        key={point.tool}
                        title={
                            <div className="flex flex-col gap-0.5">
                                <span className="font-semibold font-mono">{point.tool}</span>
                                <span>Description fit {point.fit.toFixed(2)}</span>
                                <span>Discovery rate {point.discoveryRatePct.toFixed(1)}%</span>
                                <span>{humanFriendlyNumber(point.callCount)} calls</span>
                            </div>
                        }
                    >
                        <circle
                            cx={scale(point.fit, fitDomain, plotX)}
                            cy={scale(point.discoveryRatePct, [0, 100], plotY)}
                            r={radius(point.callCount, maxCalls)}
                            fill="var(--accent)"
                            fillOpacity={0.55}
                            stroke="var(--accent)"
                            className="cursor-help"
                        />
                    </Tooltip>
                ))}
            </svg>
            {unplotted > 0 ? (
                <span className="text-[10px] text-muted">
                    {unplotted} tool{unplotted === 1 ? ' is' : 's are'} not plotted: they lack a captured description or
                    enough advertised sessions to measure discovery.
                </span>
            ) : null}
        </div>
    )
}
