import { useActions, useValues } from 'kea'

import { Chip, ChipClose, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { teamLogic } from 'scenes/teamLogic'

import { PathsV2StepSource } from '~/queries/schema/schema-general'
import { EditorFilterProps, PropertyFilterType, PropertyOperator } from '~/types'

import { activeChipExplanation, excludedItemChips, excludedLabelsForSource } from './exclusionUtils'
import { journeysDataLogic } from './journeysDataLogic'

export function QuillJourneysExclusions({ insightProps }: EditorFilterProps): JSX.Element {
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
                <Text size="xs" variant="muted" className="m-0">
                    Exclusions apply to step sources with a naming property. To exclude a whole event, remove its step
                    source instead.
                </Text>
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
                <Text size="xs" variant="muted" className="m-0">
                    Path cleaning applies before matching. Exclude the cleaned value shown on the chart.
                </Text>
            )}
            {chips.active.length > 0 && (
                <div className="flex flex-col gap-1">
                    <Text size="xs" variant="muted" className="m-0">
                        Also excluded:
                    </Text>
                    <div className="flex flex-wrap gap-1">
                        {chips.active.map((item, index) => {
                            const source = stepSources.find(({ event }) => event === item.event) as PathsV2StepSource
                            const label = source.namingProperty ? `${item.event} with no value` : item.event
                            return (
                                <Tooltip key={index}>
                                    <TooltipTrigger render={<Chip />}>
                                        {label}
                                        <ChipClose
                                            aria-label={`Remove ${label}`}
                                            onClick={() => removeExcludedItem(item)}
                                        />
                                    </TooltipTrigger>
                                    <TooltipContent>{activeChipExplanation(item, source)}</TooltipContent>
                                </Tooltip>
                            )
                        })}
                    </div>
                </div>
            )}
            {chips.inert.length > 0 && (
                <div className="flex flex-col gap-1">
                    <Text size="xs" variant="muted" className="m-0">
                        Not applied. No step source produces these items:
                    </Text>
                    <div className="flex flex-wrap gap-1">
                        {chips.inert.map((item, index) => (
                            <Chip key={index}>
                                {item.label || item.event}
                                <ChipClose
                                    aria-label={`Remove ${item.label || item.event}`}
                                    onClick={() => removeExcludedItem(item)}
                                />
                            </Chip>
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}
