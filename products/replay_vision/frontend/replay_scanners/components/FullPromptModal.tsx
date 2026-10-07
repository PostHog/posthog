import { LemonModal } from '@posthog/lemon-ui'

export function FullPromptModal({
    prompt,
    isOpen,
    onClose,
}: {
    prompt: string
    isOpen: boolean
    onClose: () => void
}): JSX.Element {
    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title="Prompt" width={720}>
            <div className="whitespace-pre-wrap font-mono text-sm bg-surface-tertiary border rounded p-3">{prompt}</div>
        </LemonModal>
    )
}
