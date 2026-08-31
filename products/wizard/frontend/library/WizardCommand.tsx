import { IconCheck } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet/CodeSnippet'

export function WizardCommand({
    command,
    showCopyButton,
    copied,
    onCopy,
    onCopied,
}: {
    command: string
    showCopyButton: boolean
    copied: boolean
    onCopy: () => void
    onCopied: () => void
}): JSX.Element {
    return (
        <div className="space-y-2">
            <CodeSnippet
                language={Language.Text}
                thing="Wizard command"
                onCopy={onCopied}
                className="[&_.CodeSnippet__actions]:!bg-gray-900 [&_.CodeSnippet__actions_.LemonButton]:!border-0 [&_.CodeSnippet__actions_.LemonButton]:!bg-transparent [&_.CodeSnippet__actions_.LemonButton]:!shadow-none [&_.LemonButton]:![--lemon-button-color:#fff] [&_code]:!font-normal [&_code]:!text-gray-100 [&_pre]:!border-gray-900 [&_pre]:!bg-gray-900 [&_pre]:!px-4 [&_pre]:!py-4"
            >
                {command}
            </CodeSnippet>
            {showCopyButton && (
                <LemonButton type="secondary" onClick={onCopy}>
                    Copy command
                </LemonButton>
            )}
            {copied && (
                <div className="flex items-center gap-1 text-sm font-medium text-success">
                    <IconCheck /> Command copied.
                </div>
            )}
        </div>
    )
}
