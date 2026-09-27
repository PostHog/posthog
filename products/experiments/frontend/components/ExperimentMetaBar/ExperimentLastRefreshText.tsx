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

    return <span className={colorClass}>{lastRefresh ? <TZLabel time={lastRefresh} /> : 'a while ago'}</span>
}
