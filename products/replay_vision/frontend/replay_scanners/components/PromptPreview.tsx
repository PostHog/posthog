import { useState } from 'react'

import { LemonModal } from '@posthog/lemon-ui'

import { ClippedPreview } from './ClippedPreview'

export function PromptPreview({ prompt, dataAttr }: { prompt: string; dataAttr: string }): JSX.Element {
    const [open, setOpen] = useState(false)
    return (
        <div className="bg-surface-secondary border rounded p-2">
            <ClippedPreview
                clip="short"
                buttonLabel="Show full prompt"
                dataAttr={dataAttr}
                onOpenFull={() => setOpen(true)}
            >
                <div className="whitespace-pre-wrap text-sm">{prompt}</div>
            </ClippedPreview>
            <LemonModal isOpen={open} onClose={() => setOpen(false)} title="Prompt" width={720}>
                <div className="whitespace-pre-wrap font-mono text-sm bg-surface-tertiary border rounded p-3">
                    {prompt}
                </div>
            </LemonModal>
        </div>
    )
}
