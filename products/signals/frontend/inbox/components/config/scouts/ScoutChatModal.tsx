import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconDocument } from '@posthog/icons'
import { LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import type { ScoutChatRequest } from '../../../logics/scoutFleetLogic'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { useScoutCreateDisabledReason } from './ScoutCreateModalHost'

/** Matches `SCOUT_AUTHOR_USER_PROMPT_MAX_LENGTH` on the chat endpoint. */
export const SCOUT_CHAT_PROMPT_MAX_LENGTH = 2000

export interface ScoutChatTemplate {
    id: string
    label: string
    prompt: string
}

/** Starter requests for the agent, not finished scouts, so each one stays short. */
export const SCOUT_CHAT_TEMPLATES: ScoutChatTemplate[] = [
    {
        id: 'new_errors',
        label: 'New errors, not localhost',
        prompt: 'Tell me when a new error starts spiking in production. Ignore anything from localhost or dev hosts.',
    },
    {
        id: 'spam_signups',
        label: 'Spam signups',
        prompt: 'Find signups that look like spam or bots, and tell me when a new wave of them starts.',
    },
    {
        id: 'churn_risk',
        label: 'Churn risk',
        prompt: 'Watch for active customers whose usage drops sharply, so we can reach out before they churn.',
    },
    {
        id: 'checkout_drop_off',
        label: 'Checkout drop-off',
        prompt: 'Tell me when conversion through the checkout funnel drops, and which step people leave at.',
    },
]

export interface ScoutChatModalProps {
    /** The text the prompt opens with, for example the description carried over from the form. */
    initialPrompt?: string
    onClose: () => void
    /** Opens the form instead, with what the person typed so far. */
    onSwitchToForm: (prompt: string) => void
}

/** Collects what the new scout should watch, then starts an authoring chat that opens on it. */
export function ScoutChatModal({ initialPrompt = '', onClose, onSwitchToForm }: ScoutChatModalProps): JSX.Element {
    const [prompt, setPrompt] = useState(initialPrompt)
    const [templateId, setTemplateId] = useState<string | null>(null)
    const { runningChatType, aiConsentDisabledReason } = useValues(scoutFleetLogic)
    const { startScoutChatTask } = useActions(scoutFleetLogic)
    const creationDisabledReason = useScoutCreateDisabledReason()

    const isStarting = runningChatType === 'author_scout'
    const trimmedPrompt = prompt.trim()
    const startDisabledReason =
        creationDisabledReason ??
        aiConsentDisabledReason ??
        (runningChatType !== null && !isStarting ? 'Starting another task…' : null) ??
        (trimmedPrompt ? null : 'Describe what the scout should watch')

    const startChat = (): void => {
        if (startDisabledReason || isStarting) {
            return
        }
        const request: ScoutChatRequest = { userPrompt: trimmedPrompt, templateId }
        startScoutChatTask('author_scout', 'scout authoring task', undefined, request)
    }

    return (
        <LemonModal
            isOpen
            onClose={isStarting ? undefined : onClose}
            title="What should this scout watch?"
            description="Describe it in your own words. The agent looks at your data, asks what it needs, and drafts the scout for you to turn on."
            width={560}
            hasUnsavedInput={trimmedPrompt !== initialPrompt.trim()}
            footer={
                <>
                    <div className="flex-1">
                        <LemonButton
                            type="tertiary"
                            icon={<IconDocument />}
                            disabledReason={isStarting ? 'Starting the chat' : undefined}
                            onClick={() => onSwitchToForm(trimmedPrompt)}
                            data-attr="scout-chat-use-form"
                        >
                            Use the form instead
                        </LemonButton>
                    </div>
                    <LemonButton
                        type="secondary"
                        disabledReason={isStarting ? 'Starting the chat' : undefined}
                        onClick={onClose}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={isStarting}
                        disabledReason={startDisabledReason ?? undefined}
                        onClick={startChat}
                        data-attr="scout-chat-start"
                    >
                        Start chat
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                <LemonTextArea
                    autoFocus
                    value={prompt}
                    onChange={(value) => {
                        setPrompt(value)
                        if (!value.trim()) {
                            setTemplateId(null)
                        }
                    }}
                    onPressCmdEnter={startChat}
                    minRows={4}
                    maxRows={10}
                    maxLength={SCOUT_CHAT_PROMPT_MAX_LENGTH}
                    disabled={isStarting}
                    placeholder="Tell me when a new error starts spiking in production."
                    data-attr="scout-chat-prompt"
                />
                <div className="flex flex-col gap-2">
                    <span className="text-xs text-secondary">Or start from one of these</span>
                    <div className="flex flex-wrap gap-2">
                        {SCOUT_CHAT_TEMPLATES.map((template) => (
                            <LemonButton
                                key={template.id}
                                type="secondary"
                                size="xsmall"
                                active={templateId === template.id}
                                disabledReason={isStarting ? 'Starting the chat' : undefined}
                                onClick={() => {
                                    setPrompt(template.prompt)
                                    setTemplateId(template.id)
                                }}
                                data-attr={`scout-chat-template-${template.id}`}
                            >
                                {template.label}
                            </LemonButton>
                        ))}
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}
