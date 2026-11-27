import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { templateToConfiguration } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'

import { workflowSurveyPickerLogic } from 'products/surveys/frontend/components/WorkflowSurveyPicker/workflowSurveyPickerLogic'

import { workflowLogic } from '../../../workflowLogic'
import { hogFlowEditorLogic } from '../../hogFlowEditorLogic'
import type { HogFlowAction } from '../../types'
import {
    HIDE_SURVEY_TEMPLATE_ID,
    getAwaitedSurveyId,
    getNextAction,
    insertSurveyResponseWait,
    retargetSurveyResponseWait,
} from '../surveyResponseWait'

type FunctionConfig = Extract<HogFlowAction, { type: 'function' }>['config']

function addWaitDisabledReason(
    surveyId: string | null,
    surveyUnavailable: boolean,
    templateLoaded: boolean,
    hasSingleNextStep: boolean
): string | undefined {
    if (!surveyId) {
        return 'Pick a survey first'
    }
    if (surveyUnavailable) {
        return 'Pick a survey that still exists'
    }
    if (!templateLoaded) {
        return 'Loading...'
    }
    return hasSingleNextStep ? undefined : "This step doesn't lead to a single next step"
}

function RetargetWaitBanner({
    actionId,
    surveyId,
    surveyUnavailable,
}: {
    actionId: string
    surveyId: string
    surveyUnavailable: boolean
}): JSX.Element {
    const { workflow } = useValues(workflowLogic)
    const { setWorkflowInfo } = useActions(workflowLogic)

    const retargetWait = (): void => {
        const result = retargetSurveyResponseWait(workflow, actionId, surveyId)
        if (result) {
            setWorkflowInfo(result)
        }
    }

    return (
        <LemonBanner
            type="warning"
            action={{
                children: 'Wait for this survey',
                onClick: retargetWait,
                disabledReason: surveyUnavailable ? 'Pick a survey that still exists' : undefined,
                'data-attr': 'workflow-survey-retarget-answer-wait',
            }}
        >
            The next step waits for an answer to a different survey.
        </LemonBanner>
    )
}

export function SurveyResponseWaitConfiguration({
    actionId,
    surveyId,
}: {
    actionId: string
    surveyId: string | null
}): JSX.Element | null {
    const { workflow, hogFunctionTemplatesById } = useValues(workflowLogic)
    const { setWorkflowInfo } = useActions(workflowLogic)
    const { setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const { selectedSurvey, selectedSurveyLoading } = useValues(workflowSurveyPickerLogic({ surveyId }))
    const surveyUnavailable =
        !!surveyId && !selectedSurveyLoading && (selectedSurvey?.id !== surveyId || !!selectedSurvey?.archived)

    const awaitedSurveyId = getAwaitedSurveyId(getNextAction(workflow, actionId))

    if (awaitedSurveyId) {
        return awaitedSurveyId === surveyId || !surveyId ? null : (
            <RetargetWaitBanner actionId={actionId} surveyId={surveyId} surveyUnavailable={surveyUnavailable} />
        )
    }

    const hideSurveyTemplate = hogFunctionTemplatesById[HIDE_SURVEY_TEMPLATE_ID]

    const addWait = (): void => {
        if (!surveyId || !hideSurveyTemplate) {
            return
        }
        const hideSurveyConfig = {
            template_id: HIDE_SURVEY_TEMPLATE_ID,
            inputs: templateToConfiguration(hideSurveyTemplate).inputs ?? {},
        } as FunctionConfig
        const result = insertSurveyResponseWait(workflow, actionId, surveyId, hideSurveyConfig)
        if (!result) {
            return
        }
        setWorkflowInfo({ actions: result.actions, edges: result.edges })
        setSelectedNodeId(result.waitActionId)
        // pinned: analytics event name
        posthog.capture('workflow survey answer wait added')
    }

    return (
        <div className="flex flex-col gap-2 rounded border p-3">
            <div className="font-semibold">Wait for an answer</div>
            <div className="text-xs text-secondary">
                Adds a step that waits up to 3 days for this person to answer, with one path for an answer and one for
                no answer. Both paths then hide the survey, so it doesn't keep showing.
            </div>
            <div>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={addWait}
                    data-attr="workflow-survey-add-answer-wait"
                    disabledReason={addWaitDisabledReason(
                        surveyId,
                        surveyUnavailable,
                        !!hideSurveyTemplate,
                        getNextAction(workflow, actionId) !== undefined
                    )}
                >
                    Add wait for answer
                </LemonButton>
            </div>
        </div>
    )
}
