import { IconMarkdown, IconMarkdownFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { JSONViewer } from 'lib/components/JSONViewer'
import { IconExclamation } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { useState } from 'react'

import { LLMInputOutput } from '../LLMInputOutput'
import { CompatMessage } from '../types'
import { normalizeMessages } from '../utils'

export function ConversationMessagesDisplay({
    input,
    output,
    httpStatus,
    bordered = false,
}: {
    input: any
    output: any
    httpStatus?: number
    bordered?: boolean
}): JSX.Element {
    const inputNormalized = normalizeMessages(input, 'user')
    const outputNormalized = normalizeMessages(output, 'assistant')

    return (
        <LLMInputOutput
            inputDisplay={
                inputNormalized?.map((message, i) => (
                    <>
                        <LLMMessageDisplay key={i} message={message} />
                        {i < inputNormalized.length - 1 && (
                            <div className="border-l ml-2 h-2" /> /* Spacer connecting messages visually */
                        )}
                    </>
                )) || (
                    <div className="rounded border text-default p-2 italic bg-[var(--background-danger-subtle)]">
                        No input
                    </div>
                )
            }
            outputDisplay={
                outputNormalized?.map((message, i) => <LLMMessageDisplay key={i} message={message} isOutput />) || (
                    <div className="flex items-center gap-1.5 rounded border text-default p-2 font-medium bg-[var(--background-danger-subtle)]">
                        <IconExclamation className="text-base" />
                        {httpStatus ? `Generation failed with HTTP status ${httpStatus}` : 'Missing output'}
                    </div>
                )
            }
            outputHeading={`Output${outputNormalized && outputNormalized.length > 1 ? ' (multiple choices)' : ''}`}
            bordered={bordered}
        />
    )
}

export function LLMMessageDisplay({ message, isOutput }: { message: CompatMessage; isOutput?: boolean }): JSX.Element {
    const [isRenderingMarkdown, setIsRenderingMarkdown] = useState(!!message.content)

    const { role, content, ...additionalKwargs } = message
    const additionalKwargsEntries = Object.entries(additionalKwargs).filter(([, value]) => value !== undefined)

    return (
        <div
            className={clsx(
                'rounded border text-default',
                isOutput
                    ? 'bg-[var(--bg-fill-success-tertiary)]'
                    : role === 'user'
                    ? 'bg-[var(--bg-fill-tertiary)]'
                    : role === 'assistant'
                    ? 'bg-[var(--bg-fill-info-tertiary)]'
                    : null // e.g. system
            )}
        >
            <div className="flex items-center gap-1 w-full px-2 h-6 text-xs font-medium">
                <span className="grow">{role}</span>
                {content && (
                    <>
                        <LemonButton
                            size="small"
                            noPadding
                            icon={isRenderingMarkdown ? <IconMarkdownFilled /> : <IconMarkdown />}
                            tooltip="Toggle Markdown rendering"
                            onClick={() => setIsRenderingMarkdown(!isRenderingMarkdown)}
                        />
                        <CopyToClipboardInline iconSize="small" description="message content" explicitValue={content} />
                    </>
                )}
            </div>
            {!!content && (
                <div className={clsx('p-2 whitespace-pre-wrap border-t', !isRenderingMarkdown && 'font-mono text-xs')}>
                    {isRenderingMarkdown ? <LemonMarkdown>{content}</LemonMarkdown> : content}
                </div>
            )}
            {!!additionalKwargsEntries && additionalKwargsEntries.length > 0 && (
                <div className="p-2 text-xs border-t">
                    {additionalKwargsEntries.map(([key, value]) => (
                        <JSONViewer
                            key={key}
                            name={key}
                            src={value}
                            // `collapsed` limits depth shown at first. 4 is chosen so that we do show
                            // function arguments in `tool_calls`, but if an argument is an object,
                            // its child objects are collapsed by default
                            collapsed={4}
                        />
                    ))}
                </div>
            )}
        </div>
    )
}
