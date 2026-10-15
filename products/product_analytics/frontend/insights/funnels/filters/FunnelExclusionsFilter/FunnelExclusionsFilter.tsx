import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { SeriesActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { funnelDataLogic } from 'products/product_analytics/frontend/insights/funnels/funnelDataLogic'

import { ExclusionRow } from './ExclusionRow'
import { ExclusionRowSuffix } from './ExclusionRowSuffix'

export function FunnelExclusionsFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { funnelsFilter, newExclusionDefaults, isFunnelWithEnoughSteps } = useValues(funnelDataLogic(insightProps))
    const { updateExclusions } = useActions(funnelDataLogic(insightProps))

    const ref = useRef(null)

    const typeKey = `${keyForInsightLogicProps('new')(insightProps)}-FunnelExclusionsFilter`

    return (
        <div data-attr="funnel-exclusions-filter">
            <SeriesActionFilter
                ref={ref}
                series={funnelsFilter?.exclusions ?? []}
                onChange={updateExclusions}
                typeKey={typeKey}
                newSeriesDefaults={newExclusionDefaults}
                disabled={!isFunnelWithEnoughSteps}
                buttonCopy="Add exclusion"
                actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
                mathAvailability={MathAvailability.None}
                hideFilter
                hideRename
                hideDeleteBtn
                seriesIndicatorType="alpha"
                renderRow={(props) => <ExclusionRow {...props} />}
                customRowSuffix={(props) => <ExclusionRowSuffix typeKey={typeKey} {...props} />}
                filtersLeftPadding={true}
            />
        </div>
    )
}
