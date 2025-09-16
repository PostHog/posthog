import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
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
    const _setFilters = (filters: FilterType): void => {
        // TODO: Improve the types here...
        setFilters(filters as HogFlowAction['filters'])
    }
    return (
        <ActionFilter
            filters={filters ?? {}}
            setFilters={_setFilters}
            typeKey={typeKey ?? 'hogflow-filters'}
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
            buttonCopy={buttonCopy ?? 'Add filter'}
        />
    )
}

export function HogFlowPropertyFilters({ actionId, filters, setFilters }: HogFlowFiltersProps): JSX.Element {
    const _setFilters = (properties: FilterType['properties']): void => {
        setFilters({ ...filters, properties: properties ?? [] } as HogFlowAction['filters'])
    }

    return (
        <PropertyFilters
            propertyFilters={filters?.properties}
            onChange={_setFilters}
            pageKey={`HogFlowPropertyFilters.${actionId}`}
            taxonomicGroupTypes={[
                TaxonomicFilterGroupType.PersonProperties,
                TaxonomicFilterGroupType.Cohorts,
                TaxonomicFilterGroupType.HogQLExpression,
            ]}
            metadataSource={{ kind: NodeKind.ActorsQuery }}
        />
    )
}
