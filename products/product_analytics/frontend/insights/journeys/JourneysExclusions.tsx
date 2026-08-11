import { useActions, useValues } from 'kea'

import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { teamLogic } from 'scenes/teamLogic'

import { PathsV2Item, PathsV2StepSource } from '~/queries/schema/schema-general'
import { EditorFilterProps, PropertyFilterType, PropertyOperator } from '~/types'

import { excludedItemChips, excludedLabelsForSource } from './exclusionUtils'
import { journeysDataLogic } from './journeysDataLogic'

function activeChipExplanation(item: PathsV2Item, source: PathsV2StepSource): string {
    if (source.namingProperty) {
        return `Excludes ${item.event} events with no value for ${source.namingProperty}.`
    }
    return `Excludes all ${item.event} events.`
}

export function JourneysExclusions({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsV2Filter, stepSources, excludedItems } = useValues(journeysDataLogic(insightProps))
    const { setExcludedLabels, removeExcludedItem } = useActions(journeysDataLogic(insightProps))
    const { currentTeam } = useValues(teamLogic)

    const namingSources = stepSources.filter((source) => source.namingProperty)
    const chips = excludedItemChips(excludedItems, stepSources)
    const hasCleaningRules =
        ((pathsV2Filter?.applyTeamPathCleaning ?? true) && (currentTeam?.path_cleaning_filters || []).length > 0) ||
        (pathsV2Filter?.localPathCleaningFilters ?? []).length > 0

    return (
        <div className="flex flex-col gap-2">
            {namingSources.length === 0 && (
                <div className="text-secondary">
                    Exclusions apply to step sources with a naming property. To exclude a whole event, remove its step
                    source instead.
                </div>
            )}
            {namingSources.map((source) => (
                <div key={source.event} className="flex flex-col gap-1">
                    {namingSources.length > 1 && (
                        <PropertyKeyInfo value={source.event} type={TaxonomicFilterGroupType.Events} disablePopover />
                    )}
                    <PropertyValue
                        propertyKey={source.namingProperty as string}
                        type={PropertyFilterType.Event}
                        operator={PropertyOperator.Exact}
                        eventNames={[source.event]}
                        value={excludedLabelsForSource(excludedItems, source)}
                        onSet={(labels: string[]) => setExcludedLabels(source, labels ?? [])}
                        placeholder="Values to exclude"
                    />
                </div>
            ))}
            {namingSources.length > 0 && hasCleaningRules && (
                <div className="text-secondary text-xs">
                    Path cleaning applies before matching. Exclude the cleaned value shown on the chart.
                </div>
            )}
            {chips.active.length > 0 && (
                <div className="flex flex-col gap-1">
                    <div className="text-secondary">Also excluded:</div>
                    <div className="flex flex-wrap gap-1">
                        {chips.active.map((item, index) => {
                            const source = stepSources.find(({ event }) => event === item.event) as PathsV2StepSource
                            return (
                                <Tooltip key={index} title={activeChipExplanation(item, source)}>
                                    <LemonSnack onClose={() => removeExcludedItem(item)}>
                                        {source.namingProperty ? `${item.event} with no value` : item.event}
                                    </LemonSnack>
                                </Tooltip>
                            )
                        })}
                    </div>
                </div>
            )}
            {chips.inert.length > 0 && (
                <div className="flex flex-col gap-1">
                    <div className="text-secondary">Not applied. No step source produces these items:</div>
                    <div className="flex flex-wrap gap-1">
                        {chips.inert.map((item, index) => (
                            <LemonSnack key={index} onClose={() => removeExcludedItem(item)}>
                                {item.label || item.event}
                            </LemonSnack>
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}
