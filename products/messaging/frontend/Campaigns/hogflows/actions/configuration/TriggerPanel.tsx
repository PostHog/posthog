import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { HogFlowActionPanelProps } from '../../types'

export function TriggerPanelOptions({ action }: HogFlowActionPanelProps<'trigger'>): JSX.Element {
    const { filters } = action.action.config

    console.log('filters', filters)

    return (
        <>
            <div className="flex flex-col">
                <p className="mb-1 text-lg font-semibold">Campaign trigger event</p>
                <p className="mb-0">Choose which events or actions will enter a user into the campaign.</p>
            </div>
            <ActionFilter
                filters={filters ?? {}}
                setFilters={(filters) => action.partialUpdateConfig({ filters })}
                typeKey="campaign-trigger"
                mathAvailability={MathAvailability.None}
                hideRename
                hideDuplicate
                showNestedArrow={false}
                actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
                propertiesTaxonomicGroupTypes={[
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.EventFeatureFlags,
                    TaxonomicFilterGroupType.Elements,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.HogQLExpression,
                ]}
                propertyFiltersPopover
                addFilterDefaultOptions={{
                    id: '$pageview',
                    name: '$pageview',
                    type: 'events',
                }}
                buttonProps={{
                    type: 'secondary',
                }}
                buttonCopy="Add trigger event"
            />
        </>
    )
}
