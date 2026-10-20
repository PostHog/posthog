import { useState } from 'react'

import { ClippedPreview } from './ClippedPreview'
import { FullPromptModal } from './FullPromptModal'

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
            <FullPromptModal prompt={prompt} isOpen={open} onClose={() => setOpen(false)} />
        </div>
    )
}
