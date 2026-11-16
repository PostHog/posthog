import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import type { AnyPropertyFilter, InsightLogicProps } from '~/types'

import type { InsightDataCheckApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { insightDataChecksLogic } from './insightDataChecksLogic'
import { withPropertyFilter } from './withPropertyFilter'

export function ExcludeFromInsightButton({
    insightProps,
    check,
}: {
    insightProps: InsightLogicProps
    check: InsightDataCheckApi
}): JSX.Element | null {
    const logic = insightDataChecksLogic(insightProps)
    const { querySource, status } = useValues(logic)
    const { excludeFromInsight, reportButtonClicked } = useActions(logic)

    if (!check.filter_to_add) {
        return null
    }
    const fits = withPropertyFilter(querySource?.properties, check.filter_to_add as AnyPropertyFilter) !== null

    return (
        <Button
            variant="outline"
            size="sm"
            loading={status === 'checking'}
            disabledReason={
                fits
                    ? undefined
                    : "This insight's filters use OR groups. Add the rule in the insight's filters instead."
            }
            onClick={() => {
                reportButtonClicked('exclude_from_insight', check.key)
                excludeFromInsight(check)
            }}
            data-attr="insight-data-check-exclude-from-insight"
        >
            Exclude from this insight
        </Button>
    )
}
