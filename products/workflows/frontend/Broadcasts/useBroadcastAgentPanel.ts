import { useValues } from 'kea'
import { useMemo } from 'react'

import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'
import { sceneAgentPanelLogic } from 'scenes/max/sceneAgentPanelLogic'
import { useSceneAgentPanel } from 'scenes/max/useSceneAgentPanel'

import { HogFunctionTemplateType } from '~/types'

import { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import type { HogFlow } from '../Workflows/hogflows/types'
import { EMAIL_EDITOR_AGENT_HEADLINES, buildWorkflowAgentContext } from '../Workflows/workflowAgentContext'
import { EMAIL_ACTION_ID, broadcastWizardLogic } from './broadcastWizardLogic'

// The context builder redacts every input of a step whose template it cannot find. The broadcast's only
// function step uses template-email, whose single input is the email itself and holds no secret.
const BROADCAST_TEMPLATES: Record<string, HogFunctionTemplateType> = {
    'template-email': {
        id: 'template-email',
        inputs_schema: [{ key: 'email', type: 'email' }],
    } as unknown as HogFunctionTemplateType,
}

// Static text, so it is safe as a trusted instruction. The wizard rewrites the graph on every save,
// so graph edits would be lost, and launching belongs to the wizard's review step.
const BROADCAST_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: 'broadcast-content',
    value:
        'This workflow is a broadcast: a batch trigger, one email step and an exit. Change only the email step ' +
        '(its content, subject and preheader). Do not add, remove or reorder steps, and do not enable or ' +
        'publish it. The user launches it from the broadcast wizard. An email edit only saves once the step has ' +
        'a sender, so if from.integrationId is empty, ask the user to pick one in the From field first.',
}

/**
 * Attaches the saved broadcast to PostHog AI on every wizard step, so a run that lands on review still
 * knows the email it is refining. The panel only opens itself on the content step.
 */
export function useBroadcastAgentPanel(): void {
    const { broadcastAsWorkflow, broadcastId, currentStep } = useValues(broadcastWizardLogic)
    const { sceneIntegrationEnabled } = useValues(sceneAgentPanelLogic)
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
}
