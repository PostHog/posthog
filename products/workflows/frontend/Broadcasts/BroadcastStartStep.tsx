import { useActions } from 'kea'
import { router } from 'kea-router'
import { useRef, useState } from 'react'

import { IconArrowLeft, IconArrowRight, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { useMaxTool } from 'scenes/max/useMaxTool'
import { urls } from 'scenes/urls'

import { broadcastWizardLogic } from './broadcastWizardLogic'

export function BroadcastStartStep(): JSX.Element {
    const { openFullEditor } = useActions(broadcastWizardLogic)
    const [prompt, setPrompt] = useState('')
    const textAreaRef = useRef<HTMLTextAreaElement>(null)

    const { openMax } = useMaxTool({
        identifier: 'create_broadcast',
        initialMaxPrompt: `!${prompt.trim()}`,
        callback: (toolOutput) => {
            const id = (toolOutput as { broadcast_id?: string })?.broadcast_id
            if (id) {
                router.actions.push(urls.broadcast(id))
            }
        },
    })

    const submit = (): void => {
        if (prompt.trim()) {
            openMax?.()
            setPrompt('')
        }
    }

    return (
        <div className="mx-auto w-full max-w-3xl space-y-6 px-6 py-6">
            <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} to={urls.broadcasts()}>
                Broadcasts
            </LemonButton>

            <div className="text-center space-y-2">
                <h1 className="text-2xl font-semibold">Send a broadcast</h1>
                <p className="text-secondary">
                    Describe the email and who should get it. You can review everything before anything sends.
                </p>
            </div>

            <div className="rounded-xl border-2 border-[var(--color-ai)]">
                <label
                    htmlFor="broadcast-ai-prompt"
                    className="flex flex-col cursor-text"
                    onClick={() => textAreaRef.current?.focus()}
                >
                    <LemonTextArea
                        id="broadcast-ai-prompt"
                        ref={textAreaRef}
                        value={prompt}
                        onChange={setPrompt}
                        onPressEnter={submit}
                        placeholder="e.g., Email everyone on the pro plan about the new dashboard"
                        minRows={2}
                        maxRows={5}
                        className="!border-none !bg-transparent !shadow-none !rounded-none px-4 pt-4 pb-2 resize-none text-sm"
                        hideFocus
                        data-attr="broadcast-ai-prompt-input"
                    />
                    <div className="flex items-center justify-between px-4 pb-3">
                        <div className="flex items-center gap-1.5 text-xs text-tertiary">
                            <IconSparkles className="text-ai size-3.5" />
                            <span>PostHog AI</span>
                        </div>
                        <LemonButton
                            type="primary"
                            size="small"
                            icon={<IconArrowRight />}
                            onClick={submit}
                            disabledReason={!prompt.trim() ? 'Describe the broadcast you want' : undefined}
                            data-attr="broadcast-ai-prompt-submit"
                        >
                            Create with AI
                        </LemonButton>
                    </div>
                </label>
            </div>

            <p className="text-center text-xs text-muted">
                Need more control?{' '}
                <button
                    type="button"
                    onClick={openFullEditor}
                    className="text-link hover:underline"
                    data-attr="broadcast-open-full-editor"
                >
                    Open full editor
                </button>
            </p>
        </div>
    )
}
