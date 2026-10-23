import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'

export function ExperimentLastRefreshText({ lastRefresh }: { lastRefresh: string | null }): JSX.Element {
    const hoursSinceRefresh = lastRefresh ? dayjs().diff(dayjs(lastRefresh), 'hours') : null
    const colorClass =
        hoursSinceRefresh === null
            ? ''
            : hoursSinceRefresh > 12
              ? 'text-danger'
              : hoursSinceRefresh > 6
                ? 'text-warning'
                : ''

    return (
        <span className={colorClass}>
            {/* align-baseline overrides TZLabel's align-middle, which sits the text a pixel below its siblings */}
            {lastRefresh ? <TZLabel time={lastRefresh} className="align-baseline" /> : 'a while ago'}
        </span>
    )
}
