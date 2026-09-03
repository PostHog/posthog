import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { Experiment } from '~/types'

import type { RunningTimeEstimateApi } from 'products/experiments/frontend/generated/api.schemas'

export const RunningTimeCell = ({
    experiment,
    estimate,
    loading,
}: {
    experiment: Experiment
    estimate: RunningTimeEstimateApi | undefined
    loading: boolean
}): JSX.Element => {
    if (loading && estimate === undefined) {
        return <Spinner />
    }

    const remainingDays = estimate?.remaining_days
    const targetSampleSize = estimate?.target_sample_size
    const currentExposures = estimate?.current_exposures

    // A negative estimate is not a real duration, so read it as "no estimate" rather than "~-N days".
    if (remainingDays === undefined || remainingDays === null || remainingDays < 0) {
        return (
            <Tooltip title="Remaining time will be calculated once the experiment has enough data">
                <div className="w-full">
                    <LemonProgress percent={0} bgColor="var(--border)" strokeColor="var(--border)" />
                </div>
            </Tooltip>
        )
    }

    if (remainingDays === 0) {
        return (
            <Tooltip title="Recommended sample size reached">
                <div className="w-full">
                    <LemonProgress percent={100} strokeColor="var(--success)" />
                </div>
            </Tooltip>
        )
    }

    // Automatic mode reports live exposures, so progress is exposures toward the target. Manual mode has
    // no exposures; measure progress by days elapsed against the total (elapsed + remaining) instead.
    let progress = 0
    if (currentExposures != null && targetSampleSize && targetSampleSize > 0) {
        progress = Math.min((currentExposures / targetSampleSize) * 100, 100)
    } else if (experiment.start_date) {
        const daysElapsed = dayjs().diff(dayjs(experiment.start_date), 'day')
        const totalDays = daysElapsed + remainingDays
        progress = totalDays > 0 ? Math.min((daysElapsed / totalDays) * 100, 100) : 0
    }

    return (
        <Tooltip title={`~${Math.ceil(remainingDays)} day${Math.ceil(remainingDays) !== 1 ? 's' : ''} remaining`}>
            <div className="w-full">
                <LemonProgress percent={progress} />
            </div>
        </Tooltip>
    )
}
