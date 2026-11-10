import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { templateToConfiguration } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'

import { workflowLogic } from '../../../workflowLogic'
import { hogFlowEditorLogic } from '../../hogFlowEditorLogic'
import type { HogFlowAction } from '../../types'
import {
    HIDE_SURVEY_TEMPLATE_ID,
    getAwaitedSurveyId,
    getNextAction,
    insertSurveyResponseWait,
} from '../surveyResponseWait'

type FunctionConfig = Extract<HogFlowAction, { type: 'function' }>['config']

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

    const awaitedSurveyId = getAwaitedSurveyId(getNextAction(workflow, actionId))

    if (awaitedSurveyId) {
        return awaitedSurveyId === surveyId ? null : (
            <LemonBanner type="warning">
                The next step waits for an answer to a different survey. Update it to wait for this one.
            </LemonBanner>
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
                    disabledReason={
                        !surveyId
                            ? 'Pick a survey first'
                            : !hideSurveyTemplate
                              ? 'Loading...'
                              : getNextAction(workflow, actionId) === undefined
                                ? "This step doesn't lead to a single next step"
                                : undefined
                    }
                >
                    Add wait for answer
                </LemonButton>
            </div>
        </div>
    )
}
