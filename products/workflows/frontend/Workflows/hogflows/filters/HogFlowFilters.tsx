import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { NodeKind } from '~/queries/schema/schema-general'
import { FilterType } from '~/types'

import { HogFlowAction } from '../types'

export type HogFlowFiltersProps = {
    actionId?: HogFlowAction['id']
    filters: HogFlowAction['filters']
    setFilters: (filters: HogFlowAction['filters']) => void
    typeKey?: string
    buttonCopy?: string
}

/**
 * Standard components wherever we do conditional matching to support whatever we know the hogflow engine supports
 */
export function HogFlowEventFilters({ filters, setFilters, typeKey, buttonCopy }: HogFlowFiltersProps): JSX.Element {
    const shouldShowInternalEvents = useFeatureFlag('WORKFLOWS_INTERNAL_EVENT_FILTERS')

    const actionsTaxonomicGroupTypes = [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]
    if (shouldShowInternalEvents) {
        actionsTaxonomicGroupTypes.push(TaxonomicFilterGroupType.InternalEvents)
    }

    const propertyTaxonomicGroupTypes = [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.EventFeatureFlags,
        TaxonomicFilterGroupType.Elements,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.HogQLExpression,
    ]
    if (shouldShowInternalEvents) {
        propertyTaxonomicGroupTypes.push(TaxonomicFilterGroupType.InternalEventProperties)
    }

    return (
        <ActionFilter
            filters={filters ?? {}}
            setFilters={(filters: FilterType): void => {
                // TODO: Improve the types here...
                setFilters(filters as HogFlowAction['filters'])
            }}
            typeKey={typeKey ?? 'hogflow-filters'}
            mathAvailability={MathAvailability.None}
            hideRename
            hideDuplicate
            showNestedArrow={false}
            actionsTaxonomicGroupTypes={actionsTaxonomicGroupTypes}
            propertiesTaxonomicGroupTypes={propertyTaxonomicGroupTypes}
            propertyFiltersPopover
            addFilterDefaultOptions={{
                id: '$pageview',
                name: '$pageview',
                type: 'events',
            }}
            buttonProps={{
                type: 'secondary',
            }}
            buttonCopy={buttonCopy ?? 'Add filter'}
        />
    )
}

export function HogFlowPropertyFilters({ actionId, filters, setFilters }: HogFlowFiltersProps): JSX.Element {
    return (
        <PropertyFilters
            propertyFilters={filters?.properties}
            onChange={(properties: FilterType['properties']): void => {
                setFilters({ ...filters, properties: properties ?? [] } as HogFlowAction['filters'])
            }}
            pageKey={`HogFlowPropertyFilters.${actionId}`}
            taxonomicGroupTypes={[
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.EventFeatureFlags,
                TaxonomicFilterGroupType.PersonProperties,
                TaxonomicFilterGroupType.Cohorts,
                TaxonomicFilterGroupType.HogQLExpression,
            ]}
            metadataSource={{ kind: NodeKind.ActorsQuery }}
        />
    )
}
