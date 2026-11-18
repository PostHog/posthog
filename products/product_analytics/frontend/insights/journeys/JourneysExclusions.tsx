import { useActions, useValues } from 'kea'

import { Chip, ChipClose, Text } from '@posthog/quill'

import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
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

function SecondaryText({
    quill,
    className,
    children,
}: {
    quill: boolean
    className?: string
    children: React.ReactNode
}): JSX.Element {
    return quill ? (
        <Text size="xs" variant="muted" className="m-0">
            {children}
        </Text>
    ) : (
        <div className={className ? `text-secondary ${className}` : 'text-secondary'}>{children}</div>
    )
}

export function JourneysExclusions({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsV2Filter, stepSources, excludedItems } = useValues(journeysDataLogic(insightProps))
    const { setExcludedLabels, removeExcludedItem } = useActions(journeysDataLogic(insightProps))
    const { currentTeam } = useValues(teamLogic)
    const quillSurface = useQuillSurface()

    const namingSources = stepSources.filter((source) => source.namingProperty)
    const chips = excludedItemChips(excludedItems, stepSources)
    const hasCleaningRules =
        ((pathsV2Filter?.applyTeamPathCleaning ?? true) && (currentTeam?.path_cleaning_filters || []).length > 0) ||
        (pathsV2Filter?.localPathCleaningFilters ?? []).length > 0

    return (
        <div className="flex flex-col gap-2">
            {namingSources.length === 0 && (
                <SecondaryText quill={quillSurface}>
                    Exclusions apply to step sources with a naming property. To exclude a whole event, remove its step
                    source instead.
                </SecondaryText>
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
                <SecondaryText quill={quillSurface} className="text-xs">
                    Path cleaning applies before matching. Exclude the cleaned value shown on the chart.
                </SecondaryText>
            )}
            {chips.active.length > 0 && (
                <div className="flex flex-col gap-1">
                    <SecondaryText quill={quillSurface}>Also excluded:</SecondaryText>
                    <div className="flex flex-wrap gap-1">
                        {chips.active.map((item, index) => {
                            const source = stepSources.find(({ event }) => event === item.event) as PathsV2StepSource
                            const label = source.namingProperty ? `${item.event} with no value` : item.event
                            const explanation = activeChipExplanation(item, source)
                            return quillSurface ? (
                                <Chip key={index} tooltip={explanation}>
                                    <span className="truncate">{label}</span>
                                    <ChipClose
                                        onClick={() => removeExcludedItem(item)}
                                        aria-label={`Remove ${label}`}
                                    />
                                </Chip>
                            ) : (
                                <Tooltip key={index} title={explanation}>
                                    <LemonSnack onClose={() => removeExcludedItem(item)}>{label}</LemonSnack>
                                </Tooltip>
                            )
                        })}
                    </div>
                </div>
            )}
            {chips.inert.length > 0 && (
                <div className="flex flex-col gap-1">
                    <SecondaryText quill={quillSurface}>
                        Not applied. No step source produces these items:
                    </SecondaryText>
                    <div className="flex flex-wrap gap-1">
                        {chips.inert.map((item, index) => {
                            const label = item.label || item.event
                            return quillSurface ? (
                                <Chip key={index}>
                                    <span className="truncate">{label}</span>
                                    <ChipClose
                                        onClick={() => removeExcludedItem(item)}
                                        aria-label={`Remove ${label}`}
                                    />
                                </Chip>
                            ) : (
                                <LemonSnack key={index} onClose={() => removeExcludedItem(item)}>
                                    {label}
                                </LemonSnack>
                            )
                        })}
                    </div>
                </div>
            )}
        </div>
    )
}
