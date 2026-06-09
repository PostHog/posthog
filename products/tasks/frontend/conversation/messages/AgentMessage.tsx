import { JSX, memo, useCallback, useState } from 'react'

import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { IconCheck, IconCopy } from '../primitives/icons'
import { MarkdownMessage } from '../primitives/MarkdownMessage'

interface AgentMessageProps {
    content: string
}

/**
 * Read-only renderer for a single agent text message.
 *
 * Mirrors the reference structure: markdown body with a left accent border and
 * a hover-revealed copy button. File-mention / inline-file-link behavior from
 * the reference is dropped here — there is no editor to open in this transcript
 * view, so links would be dead. `MarkdownMessage` handles the markdown.
 */
export const AgentMessage = memo(function AgentMessage({ content }: AgentMessageProps): JSX.Element {
    const [copied, setCopied] = useState(false)

    const handleCopy = useCallback(() => {
        void navigator.clipboard.writeText(content)
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
    }, [content])

    return (
        <div className="group/msg relative border-l-2 border-border py-1 pl-3 text-[13px] [&>*:last-child]:mb-0 [&_p]:leading-[1.9]">
            <MarkdownMessage content={content} />
            <div className="absolute top-1 left-full ml-2 opacity-0 transition-opacity group-hover/msg:opacity-100">
                <Tooltip title={copied ? 'Copied!' : 'Copy message'}>
                    <LemonButton
                        size="small"
                        icon={copied ? <IconCheck className="text-success" /> : <IconCopy />}
                        onClick={handleCopy}
                        aria-label="Copy message"
                    />
                </Tooltip>
            </div>
        </div>
    )
})
