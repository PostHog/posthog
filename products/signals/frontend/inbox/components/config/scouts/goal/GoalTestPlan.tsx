import type { ReactNode } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

function Term({ children, tip }: { children: ReactNode; tip: string }): JSX.Element {
    return (
        <Tooltip title={tip}>
            <span className="cursor-help font-semibold underline decoration-dotted decoration-1 underline-offset-4">
                {children}
            </span>
        </Tooltip>
    )
}

export function GoalTestPlan({
    audience,
    days,
    metric,
}: {
    audience: number | null
    days: number | null
    metric: string
}): JSX.Element | null {
    if (!audience && !days) {
        return null
    }
    const people = audience ? (
        <Term tip="People who reach the screen this idea changes, each day. Half see the change and half see today's version.">
            {humanFriendlyNumber(audience)} people a day
        </Term>
    ) : null
    const length = days ? (
        <Term tip="How long the test needs at this traffic to tell a real change from noise.">
            about {days} {days === 1 ? 'day' : 'days'}
        </Term>
    ) : null
    const measure = (
        <Term tip="The goal's measure. The test compares it between the two groups.">{metric.toLowerCase()}</Term>
    )
    return (
        <p className="m-0 max-w-[72ch] text-sm leading-relaxed text-secondary" data-attr="goal-test-plan">
            {people && length ? (
                <>
                    Test it on {people} for {length} to see if it moves {measure}.
                </>
            ) : people ? (
                <>{people} reach this change. The scout plans the test length once the measure has enough history.</>
            ) : (
                <>
                    A test takes {length} to see if it moves {measure}.
                </>
            )}
        </p>
    )
}
