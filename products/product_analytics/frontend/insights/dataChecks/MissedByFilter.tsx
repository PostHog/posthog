import type { InsightLogicProps } from '~/types'

import type { InsightDataCheckApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { FilterSettingsButton } from './FilterSettingsButton'
import { FixWithPostHogAIButton } from './FixWithPostHogAIButton'
import { NotCaughtByFilter } from './NotCaughtByFilter'

export function MissedByFilter({
    insightProps,
    check,
    count,
    noun,
    examples,
    fallback,
    excludeLabel,
}: {
    insightProps: InsightLogicProps
    check: InsightDataCheckApi
    count: number
    noun: string
    examples: string[]
    fallback: string
    excludeLabel: string
}): JSX.Element {
    return (
        <div className="flex flex-col items-start gap-1.5">
            <NotCaughtByFilter count={count} noun={noun} examples={examples} fallback={fallback} />
            <div className="flex flex-wrap gap-2">
                <FilterSettingsButton rule={check.filter_to_add}>{excludeLabel}</FilterSettingsButton>
                <FixWithPostHogAIButton insightProps={insightProps} check={check} />
            </div>
        </div>
    )
}
