import { IconEye, IconMarkdown, IconMarkdownFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { JSONViewer } from 'lib/components/JSONViewer'
import { IconExclamation, IconEyeHidden } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { isObject } from 'lib/utils'
import React from 'react'

import { LLMInputOutput } from '../LLMInputOutput'
import { llmObservabilityTraceLogic } from '../llmObservabilityTraceLogic'
import { CompatMessage, VercelSDKImageMessage } from '../types'
import { normalizeMessages } from '../utils'

export function ConversationMessagesDisplay({
    input,
    output,
    tools,
    httpStatus,
    raisedError,
    bordered = false,
}: {
    input: any
    output: any
    tools?: any
    httpStatus?: number
    raisedError?: boolean
    bordered?: boolean
}): JSX.Element {
    const inputNormalized = normalizeMessages(input, 'user', tools)
    const outputNormalized = normalizeMessages(output, 'assistant')

    const outputDisplay = raisedError ? (
        <div className="flex items-center gap-1.5 rounded border text-default p-2 font-medium bg-[var(--bg-fill-error-tertiary)] border-danger overflow-x-auto">
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
    ) : outputNormalized.length > 0 ? (
        outputNormalized.map((message, i) => <LLMMessageDisplay key={i} message={message} isOutput />)
    ) : (
        <div className="rounded border text-default p-2 italic bg-[var(--bg-fill-error-tertiary)]">No output</div>
    )

    return (
        <LLMInputOutput
            inputDisplay={
                inputNormalized.length > 0 ? (
                    inputNormalized.map((message, i) => (
                        <React.Fragment key={i}>
                            <LLMMessageDisplay message={message} />
                            {i < inputNormalized.length - 1 && (
                                <div className="border-l ml-2 h-2" /> /* Spacer connecting messages visually */
                            )}
                        </React.Fragment>
                    ))
                ) : (
                    <div className="rounded border text-default p-2 italic bg-[var(--bg-fill-error-tertiary)]">
                        No input
                    </div>
                )
            }
            outputDisplay={outputDisplay}
            outputHeading={raisedError ? `Error (${httpStatus})` : 'Output'}
            bordered={bordered}
        />
    )
}

export const ImageMessageDisplay = ({
    message,
}: {
    message: { content?: string | { type?: string; image?: string } }
}): JSX.Element => {
    const { content } = message
    if (typeof content === 'string') {
        return <span>{content}</span>
    } else if (content?.image) {
        return <img src={content.image} alt="User sent image" />
    }
    return <span>{content}</span>
}

export const LLMMessageDisplay = React.memo(
    ({ message, isOutput }: { message: CompatMessage; isOutput?: boolean }): JSX.Element => {
        const { role, content, ...additionalKwargs } = message
        const { isRenderingMarkdown } = useValues(llmObservabilityTraceLogic)
        const { toggleMarkdownRendering } = useActions(llmObservabilityTraceLogic)
        const [show, setShow] = React.useState(role !== 'system' && role !== 'tool')

        // Compute whether the content looks like Markdown.
        // (Heuristic: looks for code blocks, blockquotes, headings, italic, bold, underline, strikethrough)
        const isMarkdownCandidate =
            content && typeof content === 'string' ? /(\n\s*```|^>\s|#{1,6}\s|_|\*|~~)/.test(content) : false

        // Render any additional keyword arguments as JSON.
        const additionalKwargsEntries = Array.isArray(additionalKwargs.tools)
            ? // Tools are a special case of input - and we want name and description to show first for them!
              additionalKwargs.tools.map((tool) => {
                  // Handle both formats: {function: {name, description, ...}} and {toolName, toolCallType, ...}
                  if (tool.function) {
                      const { function: { name = undefined, description = undefined, ...func } = {}, ...rest } = tool
                      return {
                          function: { name, description, ...func },
                          ...rest,
                      }
                  }
                  return tool
              })
            : Object.fromEntries(Object.entries(additionalKwargs).filter(([, value]) => value !== undefined))

        const renderMessageContent = (
            content: string | { type: string; content: string } | VercelSDKImageMessage
        ): JSX.Element | null => {
            if (!content) {
                return null
            }
            const trimmed = typeof content === 'string' ? content.trim() : JSON.stringify(content).trim()

            // If content is valid JSON (we only check when it starts and ends with {} or [] to avoid false positives)
            if (
                (trimmed.startsWith('{') && trimmed.endsWith('}')) ||
                (trimmed.startsWith('[') && trimmed.endsWith(']'))
            ) {
                try {
                    const parsed = typeof content === 'string' ? JSON.parse(content) : content
                    //check if special type
                    if (parsed.type === 'image') {
                        return <ImageMessageDisplay message={parsed} />
                    }
                    if (parsed.type === 'input_image') {
                        const message = {
                            content: {
                                type: 'image',
                                image: parsed.image_url,
                            },
                        }
                        return <ImageMessageDisplay message={message} />
                    }
                    if (typeof parsed === 'object' && parsed !== null) {
                        return <JSONViewer src={parsed} name={null} collapsed={5} />
                    }
                } catch {
                    // Not valid JSON. Fall through to Markdown/plain text handling.
                }
            }

            // If the content appears to be Markdown, render based on the toggle.
            if (isMarkdownCandidate && typeof content === 'string') {
                if (isRenderingMarkdown) {
                    // Check if content has HTML-like tags that might break markdown rendering
                    const hasHtmlLikeTags = /<[^>]+>/.test(content)

                    if (hasHtmlLikeTags) {
                        // Escape HTML-like content for safer markdown rendering
                        const escapedContent = content.replace(/</g, '&lt;').replace(/>/g, '&gt;')

                        try {
                            // pre-wrap, because especially in system prompts, we want to preserve newlines even if they aren't fully Markdown-style
                            return <LemonMarkdown className="whitespace-pre-wrap">{escapedContent}</LemonMarkdown>
                        } catch {
                            // If markdown still fails, fall back to plain text
                            return <span className="font-mono whitespace-pre-wrap">{content}</span>
                        }
                    } else {
                        // pre-wrap, because especially in system prompts, we want to preserve newlines even if they aren't fully Markdown-style
                        return <LemonMarkdown className="whitespace-pre-wrap">{content}</LemonMarkdown>
                    }
                } else {
                    return <span className="font-mono whitespace-pre-wrap">{content}</span>
                }
            }

            // Fallback: render as plain text.
            return <span className="whitespace-pre-wrap">{content}</span>
        }

        return (
            <div
                className={clsx(
                    'rounded border text-default',
                    isOutput
                        ? 'bg-[var(--bg-fill-success-tertiary)] not-last:mb-2'
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
                                    onClick={toggleMarkdownRendering}
                                />
                            )}
                            <CopyToClipboardInline
                                iconSize="small"
                                description="message content"
                                explicitValue={typeof content === 'string' ? content : JSON.stringify(content)}
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
