import { useValues } from 'kea'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import type { AnomalyIntervalEnumApi } from 'products/signals/frontend/generated/api.schemas'

const BUCKET_DATE_LABELS: Record<Exclude<AnomalyIntervalEnumApi, 'hour'>, { prefix: string; formatDate: string }> = {
    day: { prefix: 'Last anomaly on ', formatDate: 'MMM D' },
    week: { prefix: 'Last anomaly in the week of ', formatDate: 'MMM D' },
    month: { prefix: 'Last anomaly in ', formatDate: 'MMMM YYYY' },
}

export interface LastAnomalyLabelProps {
    // The start of the newest anomalous bucket, in the project timezone.
    bucketStart: string
    interval: AnomalyIntervalEnumApi
}

export function LastAnomalyLabel({ bucketStart, interval }: LastAnomalyLabelProps): JSX.Element {
    const { timezone } = useValues(teamLogic)
    if (interval === 'hour') {
        // The recent order sorts by the end of the bucket, so the relative time counts from the end too.
        return (
            <span className="text-secondary text-xs">
                Last anomaly <TZLabel time={dayjs(bucketStart).add(1, 'hour')} />
            </span>
        )
    }
    const { prefix, formatDate } = BUCKET_DATE_LABELS[interval]
    // The project timezone keeps the date of the bucket, which the viewer's own timezone can move to the day before.
    return (
        <span className="text-secondary text-xs">
            {prefix}
            <TZLabel time={bucketStart} formatDate={formatDate} formatTime="" displayTimezone={timezone} />
        </span>
    )
}
