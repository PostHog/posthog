import { TooltipSurface, TooltipSwatch } from '@posthog/quill-charts'
import type { SankeyTooltipContext } from '@posthog/quill-charts'

import type { JourneyLinkMeta, JourneyNodeMeta } from './clusterJourneyGraph'

interface JourneyTooltipProps {
    hit: SankeyTooltipContext<JourneyNodeMeta, JourneyLinkMeta>['hit']
    totalSessions: number
}

function formatShare(fraction: number): string {
    return `${Math.round(fraction * 1000) / 10}%`
}

function outcomeLabel(outcome: JourneyLinkMeta['outcome'] | undefined): string | null {
    if (!outcome) {
        return null
    }
    return outcome === 'error' ? 'Error' : 'Completed'
}

export function JourneyTooltip({ hit, totalSessions }: JourneyTooltipProps): JSX.Element {
    const { title, value, color, outcome } =
        hit.kind === 'node'
            ? { title: hit.node.label, value: hit.node.value, color: hit.node.color, outcome: undefined }
            : {
                  title: `${hit.link.source.label} → ${hit.link.target.label}`,
                  value: hit.link.value,
                  color: hit.link.color,
                  outcome: hit.link.meta?.outcome,
              }
    const share = totalSessions > 0 ? value / totalSessions : 0
    const outcomeText = outcomeLabel(outcome)

    return (
        <TooltipSurface data-attr="mcp-cluster-journey-sankey-tooltip">
            <div className="flex items-center gap-2 mb-1">
                <TooltipSwatch color={color} />
                <span className="font-semibold">{title}</span>
            </div>
            <div className="flex items-center gap-2">
                <strong>{value.toLocaleString()}</strong>
                {share > 0 ? <span className="opacity-70">({formatShare(share)})</span> : null}
            </div>
            {outcomeText ? <div className="text-xs text-muted mt-1">{outcomeText}</div> : null}
        </TooltipSurface>
    )
}
