import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'

/** Results over 12 hours old read as stale, over 6 hours as ageing. */
export function refreshStaleness(lastRefresh: string | null): 'stale' | 'ageing' | null {
    const hoursSinceRefresh = lastRefresh ? dayjs().diff(dayjs(lastRefresh), 'hours') : null
    return hoursSinceRefresh === null
        ? null
        : hoursSinceRefresh > 12
          ? 'stale'
          : hoursSinceRefresh > 6
            ? 'ageing'
            : null
}

export function ExperimentLastRefreshText({ lastRefresh }: { lastRefresh: string | null }): JSX.Element {
    const staleness = refreshStaleness(lastRefresh)
    const colorClass = staleness === 'stale' ? 'text-danger' : staleness === 'ageing' ? 'text-warning' : ''

    return (
        <span className={colorClass}>
            {/* align-baseline overrides TZLabel's align-middle, which sits the text a pixel below its siblings */}
            {lastRefresh ? <TZLabel time={lastRefresh} className="align-baseline" /> : 'a while ago'}
        </span>
    )
}
