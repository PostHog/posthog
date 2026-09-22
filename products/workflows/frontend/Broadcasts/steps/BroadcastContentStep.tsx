import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { EmailTemplater, TemplatePickerModal } from 'scenes/hog-functions/email-templater/EmailTemplater'
import type { EmailFieldErrors, EmailTemplate } from 'scenes/hog-functions/email-templater/types'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { buildSampleGlobals } from '../../Workflows/hogflows/steps/components/HogFlowFunctionConfiguration'
import { BroadcastEmailValue, DEFAULT_BROADCAST_EMAIL, broadcastWizardLogic } from '../broadcastWizardLogic'

// The wizard already attaches the live email to the agent's context, so the prompt names the task
// rather than the content. A leading `!` submits it instead of only prefilling the composer.
const WRITE_WITH_AI_PROMPT = '!Write this broadcast email for me'

export function BroadcastContentStep(): JSX.Element {
    const { email, stepValidationErrors } = useValues(broadcastWizardLogic)
    const { setEmail } = useActions(broadcastWizardLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const [templatePickerOpen, setTemplatePickerOpen] = useState(false)

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
                <div className="flex items-center gap-2">
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconSparkles />}
                        onClick={() => openSidePanel(SidePanelTab.Max, WRITE_WITH_AI_PROMPT)}
                        data-attr="broadcast-wizard-write-with-ai"
                    >
                        Write with AI
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => setTemplatePickerOpen(true)}
                        data-attr="broadcast-wizard-template-picker"
                    >
                        Start from template
                    </LemonButton>
                </div>
            </div>
            <TemplatePickerModal isOpen={templatePickerOpen} onClose={() => setTemplatePickerOpen(false)} />
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
