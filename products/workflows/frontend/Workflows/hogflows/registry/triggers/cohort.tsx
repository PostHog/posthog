import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconPeople } from '@posthog/icons'
import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { cohortsModel } from '~/models/cohortsModel'

import {
    PERSON_FREQUENCY_OPTIONS,
    registerTriggerType,
} from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/triggerTypeRegistry'
import { workflowLogic } from 'products/workflows/frontend/Workflows/workflowLogic'

import { HogFlowAction } from '../../types'

export type CohortTriggerConfig = Extract<Extract<HogFlowAction, { type: 'trigger' }>['config'], { type: 'cohort' }>

export function isCohortTriggerConfig(
    config: Extract<HogFlowAction, { type: 'trigger' }>['config']
): config is CohortTriggerConfig {
    return config.type === 'cohort'
}

function StepTriggerConfigurationCohort({ node }: { node: any }): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const { cohortsById } = useValues(cohortsModel)
    const { loadCohortsByIds } = useActions(cohortsModel)

    const config = node.data.config as CohortTriggerConfig
    const validationResult = actionValidationErrorsById[node.data.id]

    useEffect(() => {
        if (config.cohort_id) {
            loadCohortsByIds({ ids: [config.cohort_id] })
        }
    }, [config.cohort_id, loadCohortsByIds])

    return (
        <div className="flex flex-col gap-2 w-full">
            <p className="mb-0 text-sm text-muted-alt">
                This workflow runs for a person when they join or leave the selected cohort. Only realtime cohorts that
                have finished calculating can start a workflow.
            </p>
            <LemonField.Pure label="Cohort" error={validationResult?.errors?.cohort_id}>
                <TaxonomicPopover
                    groupType={TaxonomicFilterGroupType.Cohorts}
                    value={config.cohort_id}
                    onChange={(cohortId) =>
                        setWorkflowActionConfig(node.data.id, { ...config, cohort_id: Number(cohortId) })
                    }
                    renderValue={(cohortId) => <>{cohortsById[cohortId]?.name ?? `Cohort ${cohortId}`}</>}
                    placeholder="Choose a cohort"
                    data-attr="workflow-cohort-trigger-cohort"
                />
            </LemonField.Pure>
            <LemonField.Pure label="Start the workflow when a person">
                <LemonSegmentedButton
                    value={config.transition}
                    onChange={(transition) => setWorkflowActionConfig(node.data.id, { ...config, transition })}
                    options={[
                        { value: 'entered', label: 'Joins the cohort' },
                        { value: 'left', label: 'Leaves the cohort' },
                    ]}
                    data-attr="workflow-cohort-trigger-transition"
                />
            </LemonField.Pure>
        </div>
    )
}

registerTriggerType({
    value: 'cohort',
    label: 'Cohort membership',
    icon: <IconPeople />,
    description: 'Trigger when a person joins or leaves a cohort',
    featureFlag: 'workflows-cohort-conditions',
    matchConfig: (config) => isCohortTriggerConfig(config),
    buildConfig: () => ({ type: 'cohort', cohort_id: null, transition: 'entered' }),
    validate: (config): { valid: boolean; errors: Record<string, string> } | null => {
        if (config.type !== 'cohort') {
            return null
        }
        if (!config.cohort_id) {
            return { valid: false, errors: { cohort_id: 'Choose a cohort' } }
        }
        return { valid: true, errors: {} }
    },
    ConfigComponent: StepTriggerConfigurationCohort,
    frequencyOptions: PERSON_FREQUENCY_OPTIONS,
    showExitConditions: true,
})
