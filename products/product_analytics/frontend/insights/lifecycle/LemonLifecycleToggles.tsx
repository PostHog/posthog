import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonLabel } from '@posthog/lemon-ui'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { groupsModel } from '~/models/groupsModel'
import { LifecycleFilter, LifecycleQuery } from '~/queries/schema/schema-general'
import { EditorFilterProps, LifecycleToggle } from '~/types'

import {
    AGGREGATION_LABEL_FOR_CUSTOM_DATA_WAREHOUSE,
    getAggregationTargetPronoun,
} from 'products/product_analytics/frontend/insights/shared/aggregationTargetUtils'

import { DEFAULT_LIFECYCLE_TOGGLES, getLifecycleTooltip, lifecycles } from './lifecycleToggleUtils'

export function LemonLifecycleToggles({ insightProps }: EditorFilterProps): JSX.Element {
    const { insightFilter, aggregationGroupTypeIndex, querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { aggregationLabel } = useValues(groupsModel)

    const toggledLifecycles = (insightFilter as LifecycleFilter)?.toggledLifecycles || DEFAULT_LIFECYCLE_TOGGLES
    const customAggregationTarget = (querySource as LifecycleQuery | null)?.customAggregationTarget === true
    const aggregationTargetLabel = customAggregationTarget
        ? AGGREGATION_LABEL_FOR_CUSTOM_DATA_WAREHOUSE
        : aggregationLabel(aggregationGroupTypeIndex)
    const aggregationTargetPronoun = getAggregationTargetPronoun(aggregationGroupTypeIndex, customAggregationTarget)

    const toggleLifecycle = (name: LifecycleToggle): void => {
        if (toggledLifecycles.includes(name)) {
            updateInsightFilter({ toggledLifecycles: toggledLifecycles.filter((n) => n !== name) })
        } else {
            updateInsightFilter({ toggledLifecycles: [...toggledLifecycles, name] })
        }
    }

    return (
        <div className="flex flex-col -mt-1 uppercase">
            {lifecycles.map((lifecycle) => (
                <LemonLabel
                    key={lifecycle.name}
                    info={getLifecycleTooltip(lifecycle.name, aggregationTargetLabel, aggregationTargetPronoun)}
                >
                    <LemonCheckbox
                        label={lifecycle.name}
                        color={lifecycle.color}
                        checked={toggledLifecycles.includes(lifecycle.name)}
                        onChange={() => toggleLifecycle(lifecycle.name)}
                    />
                </LemonLabel>
            ))}
        </div>
    )
}
