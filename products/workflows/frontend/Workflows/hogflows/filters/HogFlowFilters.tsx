import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { NodeKind } from '~/queries/schema/schema-general'
import { FilterType } from '~/types'

import { HogFlowAction } from '../types'

export type HogFlowFiltersProps = {
    filtersKey: string
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
        TaxonomicFilterGroupType.WorkflowVariables,
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
            buttonProps={{
                type: 'secondary',
            }}
            buttonCopy={buttonCopy ?? 'Add filter'}
            allowNonCapturedEvents
        />
    )
}

export function HogFlowPropertyFilters({ filtersKey, filters, setFilters }: HogFlowFiltersProps): JSX.Element {
    return (
        <PropertyFilters
            propertyFilters={filters?.properties}
            onChange={(properties: FilterType['properties']): void => {
                setFilters({ ...filters, properties: properties ?? [] } as HogFlowAction['filters'])
            }}
            pageKey={`HogFlowPropertyFilters.${filtersKey}`}
            taxonomicGroupTypes={[
                TaxonomicFilterGroupType.WorkflowVariables,
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.EventFeatureFlags,
                TaxonomicFilterGroupType.PersonProperties,
                TaxonomicFilterGroupType.HogQLExpression,
                TaxonomicFilterGroupType.EventMetadata,
            ]}
            metadataSource={{ kind: NodeKind.ActorsQuery }}
        />
    )
}
