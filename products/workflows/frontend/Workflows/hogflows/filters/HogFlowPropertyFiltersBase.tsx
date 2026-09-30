import { useValues } from 'kea'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { groupsModel } from '~/models/groupsModel'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { NodeKind } from '~/queries/schema/schema-general'
import { FilterType } from '~/types'

import { HogFlowAction } from '../types'
import { HogFlowFiltersBaseProps, WORKFLOW_OPERATOR_ALLOWLIST } from './hogFlowFiltersShared'

/**
 * Property matching restricted to what the hogflow engine supports. Reads nothing from the
 * workflow editor, so it can render outside it; HogFlowPropertyFilters wraps it for the editor.
 */
export function HogFlowPropertyFiltersBase({
    filtersKey,
    filters,
    setFilters,
    excludeGroupProperties,
    schemaColumns,
    dataWarehouseTableName,
    taxonomicGroupTypes,
    propertyAllowList,
    propertyDefinitionsOverride,
    taxonomicFilterOptionsFromProp,
    staticValueOptions,
    buttonCopy,
    inline,
    allowNew,
    propertyKeyEditable,
    singleLine,
    showRemoveButton,
    hasRowOperator,
    hogQLGlobals,
}: HogFlowFiltersBaseProps): JSX.Element {
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const isDataWarehouse = !!dataWarehouseTableName
    return (
        <PropertyFilters
            propertyFilters={filters?.properties}
            onChange={(properties: FilterType['properties']): void => {
                setFilters({ ...filters, properties: properties ?? [] } as HogFlowAction['filters'])
            }}
            pageKey={`HogFlowPropertyFilters.${filtersKey}`}
            buttonText={buttonCopy ?? 'Add filter'}
            disablePopover={inline}
            allowNew={allowNew}
            propertyKeyEditable={propertyKeyEditable}
            singleLine={singleLine}
            showRemoveButton={showRemoveButton}
            hasRowOperator={hasRowOperator}
            taxonomicGroupTypes={
                taxonomicGroupTypes ??
                // Warehouse rows are row-scoped — only the synced row's columns make sense to filter on,
                // so event/feature-flag/person/group properties don't apply here.
                (isDataWarehouse
                    ? [TaxonomicFilterGroupType.DataWarehouseProperties, TaxonomicFilterGroupType.HogQLExpression]
                    : [
                          TaxonomicFilterGroupType.WorkflowVariables,
                          TaxonomicFilterGroupType.EventProperties,
                          TaxonomicFilterGroupType.EventFeatureFlags,
                          TaxonomicFilterGroupType.PersonProperties,
                          ...(excludeGroupProperties ? [] : groupsTaxonomicTypes),
                          TaxonomicFilterGroupType.HogQLExpression,
                          TaxonomicFilterGroupType.EventMetadata,
                      ])
            }
            taxonomicFilterOptionsFromProp={taxonomicFilterOptionsFromProp}
            schemaColumns={schemaColumns}
            dataWarehouseTableName={dataWarehouseTableName}
            metadataSource={{
                kind: NodeKind.EventsQuery,
                select: defaultDataTableColumns(NodeKind.EventsQuery),
                after: '-30d',
            }}
            hogQLGlobals={hogQLGlobals}
            operatorAllowlist={WORKFLOW_OPERATOR_ALLOWLIST}
            propertyAllowList={propertyAllowList}
            propertyDefinitionsOverride={propertyDefinitionsOverride}
            staticValueOptions={staticValueOptions}
        />
    )
}
