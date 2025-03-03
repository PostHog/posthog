import { IconEye, IconMarkdown, IconMarkdownFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { JSONViewer } from 'lib/components/JSONViewer'
import { IconExclamation, IconEyeHidden } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { isObject } from 'lib/utils'
import React from 'react'

import { LLMInputOutput } from '../LLMInputOutput'
import { CompatMessage } from '../types'
import { normalizeMessages } from '../utils'

export function ConversationMessagesDisplay({
    input,
    output,
    httpStatus,
    raisedError,
    bordered = false,
}: {
    input: any
    output: any
    httpStatus?: number
    raisedError?: boolean
    bordered?: boolean
}): JSX.Element {
    const inputNormalized = normalizeMessages(input, 'user')
    const outputNormalized = normalizeMessages(output, 'assistant')

    const outputDisplay = raisedError ? (
        <div className="flex items-center gap-1.5 rounded border text-default p-2 font-medium bg-[var(--bg-fill-error-tertiary)] border-danger overflow-x-scroll">
            <IconExclamation className="text-base" />
            {isObject(output) ? (
                <JSONViewer src={output} collapsed={4} />
            ) : (
                <span className="font-mono">
                    {(() => {
                        try {
                            const parsedJson = JSON.parse(output)
                            return isObject(parsedJson) ? (
                                <JSONViewer src={parsedJson} collapsed={5} />
                            ) : (
                                JSON.stringify(output ?? null)
                            )
                        } catch {
                            return JSON.stringify(output ?? null)
                        }
                    })()}
                </span>
            )}
        </div>
    ) : (
        outputNormalized?.map((message, i) => <LLMMessageDisplay key={i} message={message} isOutput />) || (
            <div className="rounded border text-default p-2 italic bg-[var(--bg-fill-error-tertiary)]">No output</div>
        )
    )

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
                    <div className="rounded border text-default p-2 italic bg-[var(--bg-fill-error-tertiary)]">
                        No input
                    </div>
                )
            }
            outputDisplay={outputDisplay}
            outputHeading={
                raisedError
                    ? `Error (${httpStatus})`
                    : `Output${outputNormalized && outputNormalized.length > 1 ? ' (multiple choices)' : ''}`
            }
            bordered={bordered}
        />
    )
}

export const LLMMessageDisplay = React.memo(
    ({ message, isOutput }: { message: CompatMessage; isOutput?: boolean }): JSX.Element => {
        const { role, content, ...additionalKwargs } = message
        const [isRenderingMarkdown, setIsRenderingMarkdown] = React.useState(true)
        const [show, setShow] = React.useState(true)

        // Compute whether the content looks like Markdown.
        // (Heuristic: looks for code blocks, blockquotes, or headings)
        const isMarkdownCandidate = content ? /(\n\s*```|^>\s|#{1,6}\s)/.test(content) : false

        // Render any additional keyword arguments as JSON.
        const additionalKwargsEntries = Object.fromEntries(
            Object.entries(additionalKwargs).filter(([, value]) => value !== undefined)
        )

        const renderMessageContent = (content: string): JSX.Element | null => {
            if (!content) {
                return null
            }
            const trimmed = content.trim()

            // If content is valid JSON (we only check when it starts and ends with {} or [] to avoid false positives)
            if (
                (trimmed.startsWith('{') && trimmed.endsWith('}')) ||
                (trimmed.startsWith('[') && trimmed.endsWith(']'))
            ) {
                try {
                    const parsed = JSON.parse(content)
                    if (typeof parsed === 'object' && parsed !== null) {
                        return <JSONViewer src={parsed} name={null} collapsed={5} />
                    }
                } catch {
                    // Not valid JSON. Fall through to Markdown/plain text handling.
                }
            }

            // If the content appears to be Markdown, render based on the toggle.
            if (isMarkdownCandidate) {
                return isRenderingMarkdown ? (
                    <LemonMarkdown>{content}</LemonMarkdown>
                ) : (
                    <span className="font-mono text-xs whitespace-pre-wrap">{content}</span>
                )
            }

            // Fallback: render as plain text.
            return <span className="text-xs whitespace-pre-wrap">{content}</span>
        }

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
                        : null
                )}
            >
                <div className="flex items-center gap-1 w-full px-2 h-6 text-xs font-medium">
                    <span className="grow">{role}</span>
                    {content && (
                        <>
                            <LemonButton
                                size="small"
                                noPadding
                                icon={show ? <IconEyeHidden /> : <IconEye />}
                                tooltip="Toggle message content"
                                onClick={() => setShow((prev) => !prev)}
                            />
                            {isMarkdownCandidate && (
                                <LemonButton
                                    size="small"
                                    noPadding
                                    icon={isRenderingMarkdown ? <IconMarkdownFilled /> : <IconMarkdown />}
                                    tooltip="Toggle markdown rendering"
                                    onClick={() => setIsRenderingMarkdown((prev) => !prev)}
                                />
                            )}
                            <CopyToClipboardInline
                                iconSize="small"
                                description="message content"
                                explicitValue={content}
                            />
                        </>
                    )}
                </div>
                {show && !!content && <div className="p-2 border-t">{renderMessageContent(content)}</div>}
                {show && Object.keys(additionalKwargsEntries).length > 0 && (
                    <div className="p-2 text-xs border-t">
                        <JSONViewer src={additionalKwargsEntries} name={null} collapsed={5} />
                    </div>
                )}
            </div>
        )
    }
)
LLMMessageDisplay.displayName = 'LLMMessageDisplay'
