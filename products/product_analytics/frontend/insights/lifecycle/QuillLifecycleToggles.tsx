import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { Checkbox, Label, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { capitalizeFirstLetter } from 'lib/utils/strings'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { groupsModel } from '~/models/groupsModel'
import { LifecycleFilter, LifecycleQuery } from '~/queries/schema/schema-general'
import { EditorFilterProps, LifecycleToggle } from '~/types'

import {
    AGGREGATION_LABEL_FOR_CUSTOM_DATA_WAREHOUSE,
    getAggregationTargetPronoun,
} from 'products/product_analytics/frontend/insights/shared/aggregationTargetUtils'

import { DEFAULT_LIFECYCLE_TOGGLES, getLifecycleTooltip, lifecycles } from './lifecycleToggleUtils'

export function QuillLifecycleToggles({ insightProps }: EditorFilterProps): JSX.Element {
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
        <div className="flex flex-col gap-2">
            {lifecycles.map((lifecycle) => {
                const id = `lifecycle-toggle-${lifecycle.name}`
                return (
                    <div key={lifecycle.name} className="flex items-center gap-2">
                        <Checkbox
                            id={id}
                            checked={toggledLifecycles.includes(lifecycle.name)}
                            onCheckedChange={() => toggleLifecycle(lifecycle.name)}
                        />
                        <span
                            aria-hidden
                            className="size-2 shrink-0 rounded-full"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ backgroundColor: lifecycle.color }}
                        />
                        <Label htmlFor={id} className="font-normal">
                            {capitalizeFirstLetter(lifecycle.name)}
                        </Label>
                        <Tooltip>
                            <TooltipTrigger
                                render={<span className="inline-flex" tabIndex={0} aria-label="More info" />}
                            >
                                <IconInfo className="size-4 text-muted-foreground" />
                            </TooltipTrigger>
                            <TooltipContent className="max-w-80">
                                {getLifecycleTooltip(lifecycle.name, aggregationTargetLabel, aggregationTargetPronoun)}
                            </TooltipContent>
                        </Tooltip>
                    </div>
                )
            })}
        </div>
    )
}
