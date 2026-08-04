import { useActions, useValues } from 'kea'

import { PropertyValue } from 'lib/components/PropertyFilters/components/PropertyValue'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack'

import { PathsV2Item } from '~/queries/schema/schema-general'
import { EditorFilterProps, PropertyFilterType, PropertyOperator } from '~/types'

import { excludedLabelsForSource, staleExcludedItems, withExcludedLabels } from './exclusionUtils'
import { journeysDataLogic } from './journeysDataLogic'
import { DEFAULT_STEP_SOURCES } from './stepSourcePresets'

export function JourneysExclusions({ insightProps }: EditorFilterProps): JSX.Element {
    const { pathsV2Filter } = useValues(journeysDataLogic(insightProps))
    const { updateInsightFilter } = useActions(journeysDataLogic(insightProps))

    const stepSources = pathsV2Filter?.stepSources ?? DEFAULT_STEP_SOURCES
    const excludedItems = pathsV2Filter?.excludedItems ?? []
    const namingSources = stepSources.filter((source) => source.namingProperty)
    const staleItems = staleExcludedItems(excludedItems, stepSources)

    const removeItem = (item: PathsV2Item): void => {
        updateInsightFilter({ excludedItems: excludedItems.filter((existing) => existing !== item) })
    }

    if (namingSources.length === 0) {
        return (
            <div className="text-secondary">
                Exclusions apply to step sources with a naming property. To exclude a whole event, remove its step
                source instead.
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
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
                        onSet={(labels: string[]) =>
                            updateInsightFilter({
                                excludedItems: withExcludedLabels(excludedItems, source, labels ?? []),
                            })
                        }
                        placeholder="Values to exclude"
                    />
                </div>
            ))}
            {staleItems.length > 0 && (
                <div className="flex flex-col gap-1">
                    <div className="text-secondary">Not applied, as no step source matches:</div>
                    <div className="flex flex-wrap gap-1">
                        {staleItems.map((item, index) => (
                            <LemonSnack key={index} onClose={() => removeItem(item)}>
                                {item.label ?? item.event}
                            </LemonSnack>
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}
