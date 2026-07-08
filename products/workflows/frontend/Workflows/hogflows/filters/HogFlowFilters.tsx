import { useValues } from 'kea'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { isOperatorSemver } from 'lib/utils/operators'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { groupsModel } from '~/models/groupsModel'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DatabaseSchemaField, NodeKind } from '~/queries/schema/schema-general'
import { FilterType, PropertyOperator } from '~/types'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowAction } from '../types'

export const WORKFLOW_OPERATOR_ALLOWLIST = Object.values(PropertyOperator).filter((op) => !isOperatorSemver(op))

function useSampleGlobals(): Record<string, any> {
    const { workflow } = useValues(workflowLogic)
    const workflowVariables: Record<string, any> = {}
    if (workflow?.variables) {
        for (const variable of workflow.variables) {
            if (variable.type === 'string') {
                workflowVariables[variable.key] = 'example_value'
            } else if (variable.type === 'number') {
                workflowVariables[variable.key] = 123
            } else if (variable.type === 'boolean') {
                workflowVariables[variable.key] = true
            } else if (variable.type === 'dictionary' || variable.type === 'json') {
                workflowVariables[variable.key] = {}
            } else {
                workflowVariables[variable.key] = null
            }
        }
    }
    return { variables: workflowVariables }
}

export type HogFlowFiltersProps = {
    filtersKey: string
    filters: HogFlowAction['filters']
    setFilters: (filters: HogFlowAction['filters']) => void
    typeKey?: string
    buttonCopy?: string
    // Drop group-property filters from the taxonomy. The subscription matcher wakes parked
    // wait_until_condition jobs from person- and event-keyed signals only; a group-property change
    // has no such key, so a group-based wait could never be woken and would only ever time out.
    // Used by wait conditions to keep them constrained to matcher-observable signals.
    excludeGroupProperties?: boolean
    // When filtering rows of a data warehouse table, pass the selected table's columns so they appear
    // as suggestions and resolve their distinct values.
    schemaColumns?: DatabaseSchemaField[]
    dataWarehouseTableName?: string
}

/**
 * Standard components wherever we do conditional matching to support whatever we know the hogflow engine supports
 */
export function HogFlowEventFilters({
    filters,
    setFilters,
    typeKey,
    buttonCopy,
    excludeGroupProperties,
}: HogFlowFiltersProps): JSX.Element {
    const shouldShowInternalEvents = useFeatureFlag('WORKFLOWS_INTERNAL_EVENT_FILTERS')
    const sampleGlobals = useSampleGlobals()
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const actionsTaxonomicGroupTypes = [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]
    if (shouldShowInternalEvents) {
        actionsTaxonomicGroupTypes.push(TaxonomicFilterGroupType.InternalEvents)
    }

    // WorkflowVariables comes first so its dedicated tab renders first in the category list.
    // ActionFilter does not pipe `taxonomicFilterOptionsFromProp`, so the All/Suggestions tab
    // does not aggregate variables here — variable surfacing in All/Suggestions only kicks in
    // for the property-level filter (HogFlowPropertyFilters below).
    const propertyTaxonomicGroupTypes = [
        TaxonomicFilterGroupType.WorkflowVariables,
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.EventFeatureFlags,
        TaxonomicFilterGroupType.Elements,
        TaxonomicFilterGroupType.PersonProperties,
        ...(excludeGroupProperties ? [] : groupsTaxonomicTypes),
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
            buttonProps={{
                type: 'secondary',
            }}
            buttonCopy={buttonCopy ?? 'Add filter'}
            allowNonCapturedEvents
            hogQLGlobals={sampleGlobals}
            operatorAllowlist={WORKFLOW_OPERATOR_ALLOWLIST}
        />
    )
}

export function HogFlowPropertyFilters({
    filtersKey,
    filters,
    setFilters,
    excludeGroupProperties,
    schemaColumns,
    dataWarehouseTableName,
}: HogFlowFiltersProps): JSX.Element {
    const sampleGlobals = useSampleGlobals()
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { workflow } = useValues(workflowLogic)
    // Surface workflow variables in the All/Suggestions tab so a user searching by variable key
    // sees a match alongside event/person properties. The dedicated tab still works without this.
    const taxonomicFilterOptionsFromProp = {
        [TaxonomicFilterGroupType.WorkflowVariables]: (workflow?.variables ?? []).map((variable) => ({
            name: variable.key,
        })),
    }
    const isDataWarehouse = !!dataWarehouseTableName
    return (
        <PropertyFilters
            propertyFilters={filters?.properties}
            onChange={(properties: FilterType['properties']): void => {
                setFilters({ ...filters, properties: properties ?? [] } as HogFlowAction['filters'])
            }}
            pageKey={`HogFlowPropertyFilters.${filtersKey}`}
            taxonomicGroupTypes={
                // Warehouse rows are row-scoped — only the synced row's columns make sense to filter on,
                // so event/feature-flag/person/group properties don't apply here.
                isDataWarehouse
                    ? [TaxonomicFilterGroupType.DataWarehouseProperties, TaxonomicFilterGroupType.HogQLExpression]
                    : [
                          TaxonomicFilterGroupType.WorkflowVariables,
                          TaxonomicFilterGroupType.EventProperties,
                          TaxonomicFilterGroupType.EventFeatureFlags,
                          TaxonomicFilterGroupType.PersonProperties,
                          ...(excludeGroupProperties ? [] : groupsTaxonomicTypes),
                          TaxonomicFilterGroupType.HogQLExpression,
                          TaxonomicFilterGroupType.EventMetadata,
                      ]
            }
            taxonomicFilterOptionsFromProp={taxonomicFilterOptionsFromProp}
            schemaColumns={schemaColumns}
            dataWarehouseTableName={dataWarehouseTableName}
            metadataSource={{
                kind: NodeKind.EventsQuery,
                select: defaultDataTableColumns(NodeKind.EventsQuery),
                after: '-30d',
            }}
            hogQLGlobals={sampleGlobals}
            operatorAllowlist={WORKFLOW_OPERATOR_ALLOWLIST}
        />
    )
}
