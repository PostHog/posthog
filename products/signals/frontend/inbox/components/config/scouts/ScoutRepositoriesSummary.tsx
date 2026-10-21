import { LemonTag } from '@posthog/lemon-ui'

/** Tags shown before the rest become a count, so the collapsed header can't outgrow its row. */
const MAX_SUMMARY_TAGS = 3

/** Which repositories a scout is pinned to, for the collapsed header of the settings form. */
export function ScoutRepositoriesSummary({
    loading,
    repositories,
    connected,
}: {
    /** True while the lookup behind the picker is in flight, so no verdict is shown from unresolved data. */
    loading: boolean
    repositories: string[]
    /** Whether the project has a GitHub connection a scout could clone with. */
    connected: boolean
}): JSX.Element | null {
    if (loading) {
        return null
    }
    if (repositories.length === 0) {
        return <span className="text-[11.5px] text-muted">{connected ? 'None' : 'Not connected'}</span>
    }
    const shown = repositories.slice(0, MAX_SUMMARY_TAGS)
    const hiddenCount = repositories.length - shown.length
    return (
        <>
            {shown.map((repository) => (
                // An `organization/repo` name can be long enough to widen the header past the row.
                // The full name stays reachable on hover.
                <LemonTag key={repository} size="small" type="option" className="max-w-32" title={repository}>
                    <span className="min-w-0 truncate">{repository}</span>
                </LemonTag>
            ))}
            {hiddenCount > 0 ? <span className="text-[11.5px] text-muted">+{hiddenCount} more</span> : null}
            {/* A pin the project can no longer clone runs repo-less, which a reader must be able to
                see without opening the section. */}
            {connected ? null : (
                <LemonTag size="small" type="warning">
                    Disconnected
                </LemonTag>
            )}
        </>
    )
}
