/** A topic's share change versus the previous window, in percentage points. */
export function TopicTrend({ trendPp }: { trendPp: number | null }): JSX.Element {
    if (trendPp === null) {
        return <span className="text-xs text-secondary">new</span>
    }
    if (Math.abs(trendPp) < 0.05) {
        return <span className="text-xs text-secondary">flat</span>
    }
    return (
        <span className={`text-xs ${trendPp > 0 ? 'text-success' : 'text-danger'}`} translate="no">
            {`${trendPp > 0 ? '▲' : '▼'} ${Math.abs(trendPp).toFixed(1)} pp`}
        </span>
    )
}
