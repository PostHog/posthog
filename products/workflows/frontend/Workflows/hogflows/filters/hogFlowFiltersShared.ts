import { AllowedProperties, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { isOperatorSemver } from 'lib/utils/operators'

import { PropValue } from '~/models/propertyDefinitionsModel'
import { DatabaseSchemaField } from '~/queries/schema/schema-general'
import { PropertyDefinition, PropertyOperator } from '~/types'

import { HogFlowAction } from '../types'

export const WORKFLOW_OPERATOR_ALLOWLIST = Object.values(PropertyOperator).filter((op) => !isOperatorSemver(op))

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
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    propertyAllowList?: AllowedProperties
    propertyDefinitionsOverride?: PropertyDefinition[]
    /** Extra options to offer in the taxonomic filter, for events whose properties aren't stored. */
    taxonomicFilterOptionsFromProp?: Record<string, { name: string }[]>
    staticValueOptions?: (propertyKey: string) => PropValue[] | null
    inline?: boolean
    allowNew?: boolean
    propertyKeyEditable?: boolean
    singleLine?: boolean
    showRemoveButton?: boolean
    hasRowOperator?: boolean
}

/** Filter components that do not read the workflow editor's state take the SQL expression globals as a prop. */
export type HogFlowFiltersBaseProps = HogFlowFiltersProps & {
    hogQLGlobals: Record<string, any>
}
