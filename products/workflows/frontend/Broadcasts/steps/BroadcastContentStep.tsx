import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { EmailTemplater, TemplatePickerModal } from 'scenes/hog-functions/email-templater/EmailTemplater'
import type { EmailFieldErrors, EmailTemplate } from 'scenes/hog-functions/email-templater/types'
import { sceneAgentPanelLogic } from 'scenes/max/sceneAgentPanelLogic'
import { useSceneAgentPanel } from 'scenes/max/useSceneAgentPanel'

import { HogFunctionTemplateType, IntegrationType } from '~/types'

import { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import { EmailSetupModal } from '../../Channels/EmailSetup/EmailSetupModal'
import { buildSampleGlobals } from '../../Workflows/hogflows/steps/components/HogFlowFunctionConfiguration'
import type { HogFlow } from '../../Workflows/hogflows/types'
import { EMAIL_EDITOR_AGENT_HEADLINES, buildWorkflowAgentContext } from '../../Workflows/workflowAgentContext'
import {
    BroadcastEmailValue,
    DEFAULT_BROADCAST_EMAIL,
    EMAIL_ACTION_ID,
    broadcastWizardLogic,
} from '../broadcastWizardLogic'

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

export function BroadcastContentStep(): JSX.Element {
    const { email, stepValidationErrors, selectedSender, broadcastAsWorkflow, broadcastId } =
        useValues(broadcastWizardLogic)
    const { setEmail } = useActions(broadcastWizardLogic)
    const { integrations, integrationsLoading } = useValues(integrationsLogic)
    const { loadIntegrations } = useActions(integrationsLogic)
    const [templatePickerOpen, setTemplatePickerOpen] = useState(false)
    // null: closed. 'new': set up a sender. An integration: finish verifying that one.
    const [senderSetup, setSenderSetup] = useState<'new' | IntegrationType | null>(null)

    const hasSenders = !!integrations?.some((integration) => integration.kind === 'email')
    const senderUnverified = !!selectedSender && selectedSender.config?.verified !== true

    // Closing the modal after Continue also keeps the sender it created or verified.
    const closeSenderSetup = (integrationId?: number): void => {
        setSenderSetup(null)
        if (integrationId) {
            loadIntegrations()
            setEmail({ ...email, from: { ...email.from, integrationId } })
        }
    }

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
    })

    const errors = stepValidationErrors.content
    const fieldErrors: EmailFieldErrors = {
        from: errors.find((error) => error.includes('sender')),
        subject: errors.find((error) => error.includes('subject')),
        body: errors.find((error) => error.includes('content')),
    }

    return (
        <div className="flex flex-col gap-2 min-h-[36rem]">
            <div className="flex items-start justify-between gap-2">
                <div>
                    <h2 className="m-0 text-xl font-semibold">Write your email</h2>
                    <p className="m-0 text-secondary">Pick a sender, add a subject, and design the email.</p>
                </div>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => setTemplatePickerOpen(true)}
                    data-attr="broadcast-wizard-template-picker"
                >
                    Start from template
                </LemonButton>
            </div>
            <TemplatePickerModal isOpen={templatePickerOpen} onClose={() => setTemplatePickerOpen(false)} />
            {!integrationsLoading && integrations && !hasSenders ? (
                <LemonBanner
                    type="info"
                    action={{
                        children: 'Set up email sender',
                        onClick: () => setSenderSetup('new'),
                        'data-attr': 'broadcast-setup-sender',
                    }}
                >
                    Broadcasts send from your own domain. Set up a sender, then verify the domain with a few DNS
                    records.
                </LemonBanner>
            ) : senderUnverified ? (
                <LemonBanner
                    type="warning"
                    action={{
                        children: 'Verify domain',
                        onClick: () => setSenderSetup(selectedSender),
                        'data-attr': 'broadcast-verify-sender',
                    }}
                >
                    {selectedSender?.display_name} is not verified yet. You can keep writing, but the broadcast can't
                    send until its domain is verified.
                </LemonBanner>
            ) : null}
            {senderSetup ? (
                <EmailSetupModal
                    integration={senderSetup === 'new' ? undefined : senderSetup}
                    onClose={closeSenderSetup}
                    onComplete={closeSenderSetup}
                />
            ) : null}
            <EmailTemplater
                type="native_email"
                templating="liquid"
                liveChanges
                value={email as unknown as EmailTemplate}
                defaultValue={DEFAULT_BROADCAST_EMAIL as unknown as EmailTemplate}
                onChange={(value) => setEmail(value as unknown as BroadcastEmailValue)}
                variables={buildSampleGlobals({ type: 'batch' }, null)}
                fieldErrors={fieldErrors}
            />
        </div>
    )
}
