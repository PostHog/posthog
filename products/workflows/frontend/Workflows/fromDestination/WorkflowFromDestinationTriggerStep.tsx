import { useActions, useValues } from 'kea'

import { GuidedWizardSection } from 'lib/components/GuidedWizard/GuidedWizardSection'
import { GuidedWizardStepLayout } from 'lib/components/GuidedWizard/GuidedWizardStepLayout'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter/TestAccountFilter'

import { HogFlowEventFiltersBase } from '../hogflows/filters/HogFlowEventFiltersBase'
import { HogFlowPropertyFiltersBase } from '../hogflows/filters/HogFlowPropertyFiltersBase'
import { HogFlowAction } from '../hogflows/types'
import { EventTriggerFilters } from './buildHogFlowFromDestination'
import { WorkflowFromDestinationLogicProps, workflowFromDestinationLogic } from './workflowFromDestinationLogic'

// A new workflow has no variables yet, so the SQL expression editor gets none to suggest.
const NO_GLOBALS: Record<string, any> = { variables: {} }

export function WorkflowFromDestinationTriggerStep({ templateId }: WorkflowFromDestinationLogicProps): JSX.Element {
    const logic = workflowFromDestinationLogic({ templateId })
    const { triggerFilters, triggerError, showValidationErrors } = useValues(logic)
    const { setTriggerFilters } = useActions(logic)
    const filters: EventTriggerFilters = triggerFilters ?? {}

    return (
        <GuidedWizardStepLayout>
            <GuidedWizardSection
                title="Choose the trigger"
                description="Pick the events or actions that send a message. Each matching event starts a run of the workflow."
            />
            <LemonField.Pure error={showValidationErrors ? triggerError : undefined}>
                <HogFlowEventFiltersBase
                    filters={filters as HogFlowAction['filters']}
                    setFilters={(next) =>
                        setTriggerFilters({
                            ...(next as EventTriggerFilters),
                            // The event filter only returns events and actions, so carry the shared
                            // property filters and the test account toggle through.
                            properties: filters.properties,
                            filter_test_accounts: filters.filter_test_accounts,
                        })
                    }
                    filtersKey="workflow-from-destination-trigger"
                    typeKey="workflow-from-destination-trigger"
                    buttonCopy="Add trigger event"
                    hogQLGlobals={NO_GLOBALS}
                />
            </LemonField.Pure>
            <LemonField.Pure label="Additional filters" info="These filters apply to every trigger event above.">
                <HogFlowPropertyFiltersBase
                    filters={filters as HogFlowAction['filters']}
                    setFilters={(next) =>
                        setTriggerFilters({ ...filters, properties: (next as EventTriggerFilters)?.properties ?? [] })
                    }
                    filtersKey="workflow-from-destination-trigger"
                    buttonCopy="Add filter"
                    hogQLGlobals={NO_GLOBALS}
                />
            </LemonField.Pure>
            <TestAccountFilter
                filters={{ filter_test_accounts: filters.filter_test_accounts ?? false }}
                onChange={({ filter_test_accounts }) => setTriggerFilters({ ...filters, filter_test_accounts })}
            />
        </GuidedWizardStepLayout>
    )
}
