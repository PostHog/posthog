import { useValues } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/types'

import { groupsModel } from '~/models/groupsModel'
import { FilterType } from '~/types'

import { HogFlowAction } from '../types'
import { HogFlowFiltersBaseProps, WORKFLOW_OPERATOR_ALLOWLIST } from './hogFlowFiltersShared'

/**
 * Event and action matching restricted to what the hogflow engine supports. Reads nothing from the
 * workflow editor, so it can render outside it; HogFlowEventFilters wraps it for the editor.
 */
export function HogFlowEventFiltersBase({
    filters,
    setFilters,
    typeKey,
    buttonCopy,
    excludeGroupProperties,
    hogQLGlobals,
}: HogFlowFiltersBaseProps): JSX.Element {
    const shouldShowInternalEvents = useFeatureFlag('WORKFLOWS_INTERNAL_EVENT_FILTERS')
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const actionsTaxonomicGroupTypes = [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]
    if (shouldShowInternalEvents) {
        actionsTaxonomicGroupTypes.push(TaxonomicFilterGroupType.InternalEvents)
    }

    // WorkflowVariables comes first so its dedicated tab renders first in the category list.
    // ActionFilter does not pipe `taxonomicFilterOptionsFromProp`, so the All/Suggestions tab
    // does not aggregate variables here — variable surfacing in All/Suggestions only kicks in
    // for the property-level filter (HogFlowPropertyFilters).
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
            hogQLGlobals={hogQLGlobals}
            operatorAllowlist={WORKFLOW_OPERATOR_ALLOWLIST}
        />
    )
}
