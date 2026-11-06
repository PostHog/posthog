import { Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { GoalScoutWorkApi } from 'products/signals/frontend/generated/api.schemas'

import { signedPercent } from '../../../../utils/goal/format'
import { effectBounds, exposedPeople, outcomeTone } from '../../../../utils/goal/status'

const SMALL_SAMPLE = 1000

export function GoalTestResult({ item, metric }: { item: GoalScoutWorkApi; metric: string }): JSX.Element | null {
    const measured = effectBounds(item)
    const people = exposedPeople(item)
    const live = item.stage === 'live'
    if (!measured && !people) {
        return null
    }
    const smallSample = people > 0 && people < SMALL_SAMPLE && !live
    return (
        <span className="flex flex-wrap items-baseline gap-x-1.5 text-xs">
            <span className="text-secondary">
                {metric}
                {measured ? ' changed by' : ''}
            </span>
            {measured ? (
                <span className={`font-semibold tabular-nums ${outcomeTone(item.outcome).text}`}>
                    {signedPercent(measured[0])} to {signedPercent(measured[1])}
                </span>
            ) : (
                <span className="text-tertiary">{live ? 'no result yet' : 'not measured'}</span>
            )}
            {people > 0 && (
                <span className="text-tertiary tabular-nums">
                    · {humanFriendlyNumber(people)} people{live ? ' so far' : ''}
                </span>
            )}
            {smallSample && <span className="text-tertiary">·</span>}
            {smallSample && (
                <Tooltip title="With this few people the range is wide. A repeat test with more traffic would confirm it.">
                    <span className="cursor-help text-warning underline decoration-dotted underline-offset-2">
                        small sample
                    </span>
                </Tooltip>
            )}
        </span>
    )
}
