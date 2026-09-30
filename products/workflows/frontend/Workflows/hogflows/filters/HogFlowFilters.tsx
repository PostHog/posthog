import { useValues } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowEventFiltersBase } from './HogFlowEventFiltersBase'
import { HogFlowFiltersProps } from './hogFlowFiltersShared'
import { HogFlowPropertyFiltersBase } from './HogFlowPropertyFiltersBase'

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

/**
 * Standard components wherever we do conditional matching to support whatever we know the hogflow engine supports
 */
export function HogFlowEventFilters(props: HogFlowFiltersProps): JSX.Element {
    const sampleGlobals = useSampleGlobals()
    return <HogFlowEventFiltersBase {...props} hogQLGlobals={sampleGlobals} />
}

export function HogFlowPropertyFilters({
    taxonomicFilterOptionsFromProp: taxonomicFilterOptionsFromPropOverride,
    ...props
}: HogFlowFiltersProps): JSX.Element {
    const sampleGlobals = useSampleGlobals()
    const { workflow } = useValues(workflowLogic)
    // Surface workflow variables in the All/Suggestions tab so a user searching by variable key
    // sees a match alongside event/person properties. The dedicated tab still works without this.
    const taxonomicFilterOptionsFromProp = {
        [TaxonomicFilterGroupType.WorkflowVariables]: (workflow?.variables ?? []).map((variable) => ({
            name: variable.key,
        })),
        ...taxonomicFilterOptionsFromPropOverride,
    }
    return (
        <HogFlowPropertyFiltersBase
            {...props}
            taxonomicFilterOptionsFromProp={taxonomicFilterOptionsFromProp}
            hogQLGlobals={sampleGlobals}
        />
    )
}
