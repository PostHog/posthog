import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { MCPIntentClusterLongTailApi } from '../generated/api.schemas'
import { formatErrorRate, longTailLabel } from './clusterRanking'

/** One row for every intent too rare to form a group, so the list still accounts for them. */
export function LongTailRow({ longTail }: { longTail: MCPIntentClusterLongTailApi }): JSX.Element {
    return (
        <div
            className="border-t border-primary border-l-2 border-l-transparent px-2 py-1.5 text-xs flex flex-col gap-1 bg-surface-secondary"
            data-attr="mcp-cluster-long-tail"
        >
            <span className="font-medium">{longTailLabel(longTail)}</span>
            <span className="flex items-center gap-1.5 tabular-nums text-secondary">
                {humanFriendlyNumber(longTail.session_count)} session{longTail.session_count === 1 ? '' : 's'}
                <span aria-hidden>·</span>
                {humanFriendlyNumber(longTail.call_count)} calls
                <span aria-hidden>·</span>
                {formatErrorRate(longTail.error_rate_pct)} errors
            </span>
        </div>
    )
}
