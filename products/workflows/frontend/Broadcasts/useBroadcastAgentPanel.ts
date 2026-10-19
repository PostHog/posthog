import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'
import { sceneAgentPanelLogic } from 'scenes/max/sceneAgentPanelLogic'
import { useSceneAgentPanel } from 'scenes/max/useSceneAgentPanel'

import { HogFunctionTemplateType } from '~/types'

import { resolveToolCall, useToolStreamListener } from 'products/posthog_ai/frontend/api/logics'
import { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import type { HogFlow } from '../Workflows/hogflows/types'
import { EMAIL_EDITOR_AGENT_HEADLINES, buildWorkflowAgentContext } from '../Workflows/workflowAgentContext'
import {
    BROADCAST_WIZARD_STEPS,
    BROADCAST_WIZARD_STEP_LABELS,
    EMAIL_ACTION_ID,
    broadcastWizardLogic,
} from './broadcastWizardLogic'

// The context builder redacts every input of a step whose template it cannot find. The broadcast's only
// function step uses template-email, whose single input is the email itself and holds no secret.
const BROADCAST_TEMPLATES: Record<string, HogFunctionTemplateType> = {
    'template-email': {
        id: 'template-email',
        inputs_schema: [{ key: 'email', type: 'email' }],
    } as unknown as HogFunctionTemplateType,
}

const BROADCAST_EDIT_TOOLS = [
    'workflows-patch-action-email',
    'workflows-patch-graph',
    'workflows-update',
    'workflows-restore-revision',
    'workflows-discard-draft',
]

// Static text, so it is safe as a trusted instruction. The wizard reads an edit made elsewhere back into its
// recipients and email, but it rewrites the rest of the graph on save, and launching belongs to its Review step.
const BROADCAST_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: 'broadcast-content',
    value:
        'This workflow is a broadcast. The user edits it in a wizard with these steps, in order: ' +
        `${BROADCAST_WIZARD_STEPS.map((step) => BROADCAST_WIZARD_STEP_LABELS[step]).join(', ')}. ` +
        'Use these step names when you point the user to a step. You can change two things. The recipients: ' +
        'update the batch trigger step with workflows-patch-graph, setting config.filters.properties to person ' +
        'property conditions and cohort references only, because behavioral (event) conditions are not ' +
        'supported. The email: change only the email step (its content, subject and preheader). Do not add, ' +
        'remove or reorder steps, do not change the goal or the schedule, and do not enable or publish it. The ' +
        'user launches it from the Review step. An email edit only saves once the step has a sender, so if ' +
        'from.integrationId is empty, ask the user to pick one in the From field on the Content step first.',
}

/**
 * Attaches the saved broadcast to PostHog AI on every wizard step, so a run that lands on review still
 * knows the email it is refining. The panel only opens itself on the content step.
 */
export function useBroadcastAgentPanel(): void {
    const { broadcastAsWorkflow, broadcastId, currentStep } = useValues(broadcastWizardLogic)
    const { sceneIntegrationEnabled } = useValues(sceneAgentPanelLogic)
    const { loadExternalEdit } = useActions(broadcastWizardLogic)
    // Debounced so each keystroke does not re-serialize the email into the agent context.
    const debouncedWorkflow = useDebouncedValue(broadcastAsWorkflow, 500)
    const agentContextItems = useMemo(
        () =>
            sceneIntegrationEnabled && debouncedWorkflow && broadcastId
                ? [
                      ...buildWorkflowAgentContext(
                          debouncedWorkflow as unknown as HogFlow,
                          broadcastId,
                          BROADCAST_TEMPLATES,
                          // A workflow shaped like a broadcast keeps its own step ids.
                          debouncedWorkflow.actions?.find((action) => action.type === 'function_email')?.id ??
                              EMAIL_ACTION_ID
                      ),
                      BROADCAST_CONTEXT_ITEM,
                  ]
                : null,
        [sceneIntegrationEnabled, debouncedWorkflow, broadcastId]
    )
    useSceneAgentPanel({
        sceneKey: 'broadcast',
        contextItems: agentContextItems,
        headlines: EMAIL_EDITOR_AGENT_HEADLINES,
        active: !!broadcastId,
        autoOpen: currentStep === 'content',
    })
    // The edited-elsewhere stream can miss the agent's write, so reload after each edit it makes here.
    // A plain listener, not an apply-back: a composer run starts before this wizard mounts, and the
    // reload is safe to repeat.
    useToolStreamListener({
        tools: BROADCAST_EDIT_TOOLS,
        onEvent: (event) => {
            if (event.phase !== 'completed' || !broadcastId) {
                return
            }
            const targetId = resolveToolCall(event.invocation).innerInput?.id
            if (typeof targetId !== 'string' || targetId === broadcastId) {
                loadExternalEdit()
            }
        },
    })
}
