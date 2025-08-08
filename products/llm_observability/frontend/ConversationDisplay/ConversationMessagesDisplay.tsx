import { IconEye, IconMarkdown, IconMarkdownFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { HighlightedJSONViewer } from 'lib/components/HighlightedJSONViewer'
import { IconExclamation, IconEyeHidden } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { isObject } from 'lib/utils'
import React from 'react'

import { LLMInputOutput } from '../LLMInputOutput'
import { SearchHighlight } from '../SearchHighlight'
import { containsSearchQuery } from '../searchUtils'
import { llmObservabilityTraceLogic } from '../llmObservabilityTraceLogic'
import { CompatMessage, VercelSDKImageMessage } from '../types'

export function ConversationMessagesDisplay({
    inputNormalized,
    outputNormalized,
    output,
    httpStatus,
    raisedError,
    bordered = false,
    searchQuery,
}: {
    inputNormalized: CompatMessage[]
    outputNormalized: CompatMessage[]
    output: any
    httpStatus?: number
    raisedError?: boolean
    bordered?: boolean
    searchQuery?: string
}): JSX.Element {
    const {
        inputMessageShowStates,
        outputMessageShowStates,
        searchQuery: currentSearchQuery,
    } = useValues(llmObservabilityTraceLogic)
    const { initializeMessageStates, toggleMessage, showAllMessages, hideAllMessages, applySearchResults } =
        useActions(llmObservabilityTraceLogic)

    // Initialize message states when component mounts or messages change
    React.useEffect(() => {
        initializeMessageStates(inputNormalized.length, outputNormalized.length)
    }, [inputNormalized.length, outputNormalized.length, initializeMessageStates])

    // Apply search results when search query changes
    React.useEffect(() => {
        if (searchQuery?.trim()) {
            const inputMatches = inputNormalized.map((msg) => {
                const msgStr = JSON.stringify(msg)
                return containsSearchQuery(msgStr, searchQuery)
            })
            const outputMatches = outputNormalized.map((msg) => {
                const msgStr = JSON.stringify(msg)
                return containsSearchQuery(msgStr, searchQuery)
            })
            applySearchResults(inputMatches, outputMatches)
        } else if (currentSearchQuery !== searchQuery) {
            // Reset to display option defaults when search is cleared
            initializeMessageStates(inputNormalized.length, outputNormalized.length)
        }
    }, [
        searchQuery,
        currentSearchQuery,
        inputNormalized,
        outputNormalized,
        applySearchResults,
        initializeMessageStates,
    ])

    const inputButtons =
        inputNormalized.length > 0 ? (
            <div className="flex items-center gap-1">
                <LemonButton size="xsmall" onClick={() => showAllMessages('input')} icon={<IconEye />}>
                    Expand all
                </LemonButton>
                <LemonButton size="xsmall" onClick={() => hideAllMessages('input')} icon={<IconEyeHidden />}>
                    Collapse all
                </LemonButton>
            </div>
        ) : undefined

    const outputButtons =
        outputNormalized.length > 0 && !raisedError ? (
            <div className="flex items-center gap-1">
                <LemonButton size="xsmall" onClick={() => showAllMessages('output')} icon={<IconEye />}>
                    Expand all
                </LemonButton>
                <LemonButton size="xsmall" onClick={() => hideAllMessages('output')} icon={<IconEyeHidden />}>
                    Collapse all
                </LemonButton>
            </div>
        ) : undefined

    const outputDisplay = raisedError ? (
        <div className="flex items-center gap-1.5 rounded border text-default p-2 font-medium bg-[var(--bg-fill-error-tertiary)] border-danger overflow-x-auto">
            <IconExclamation className="text-base" />
            {isObject(output) ? (
                <HighlightedJSONViewer src={output} collapsed={4} searchQuery={searchQuery} />
            ) : (
                <span className="font-mono">
                    {(() => {
                        try {
                            const parsedJson = JSON.parse(output)
                            return isObject(parsedJson) ? (
                                <HighlightedJSONViewer src={parsedJson} collapsed={5} searchQuery={searchQuery} />
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
        outputNormalized.map((message, i) => (
            <LLMMessageDisplay
                key={i}
                message={message}
                show={outputMessageShowStates[i] || false}
                isOutput
                onToggle={() => toggleMessage('output', i)}
                searchQuery={searchQuery}
            />
        ))
    ) : (
        <div className="rounded border text-default p-2 italic bg-[var(--bg-fill-error-tertiary)]">No output</div>
    )

    const inputDisplay =
        inputNormalized.length > 0 ? (
            inputNormalized.map((message, i) => (
                <React.Fragment key={i}>
                    <LLMMessageDisplay
                        message={message}
                        show={inputMessageShowStates[i] || false}
                        onToggle={() => toggleMessage('input', i)}
                        searchQuery={searchQuery}
                    />
                    {i < inputNormalized.length - 1 && (
                        <div className="border-l ml-2 h-2" /> /* Spacer connecting messages visually */
                    )}
                </React.Fragment>
            ))
        ) : (
            <div className="rounded border text-default p-2 italic bg-[var(--bg-fill-error-tertiary)]">No input</div>
        )

    return (
        <LLMInputOutput
            inputDisplay={inputDisplay}
            outputDisplay={outputDisplay}
            outputHeading={raisedError ? `Error (${httpStatus})` : 'Output'}
            bordered={bordered}
            inputButtons={inputButtons}
            outputButtons={outputButtons}
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
    ({
        message,
        isOutput,
        show,
        onToggle,
        searchQuery,
    }: {
        message: CompatMessage
        isOutput?: boolean
        show: boolean
        onToggle?: () => void
        searchQuery?: string
    }): JSX.Element => {
        const { role, content, ...additionalKwargs } = message
        const { isRenderingMarkdown } = useValues(llmObservabilityTraceLogic)
        const { toggleMarkdownRendering } = useActions(llmObservabilityTraceLogic)

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
            content: string | { type: string; content: string } | VercelSDKImageMessage | object[],
            searchQuery?: string
        ): JSX.Element | null => {
            if (!content) {
                return null
            }

            // Handle array-based content
            if (Array.isArray(content)) {
                return (
                    <>
                        {content.map((item, index) => (
                            <React.Fragment key={index}>
                                {typeof item === 'string' ? (
                                    searchQuery?.trim() ? (
                                        <SearchHighlight
                                            string={item}
                                            substring={searchQuery}
                                            className="whitespace-pre-wrap"
                                        />
                                    ) : (
                                        <span className="whitespace-pre-wrap">{item}</span>
                                    )
                                ) : item &&
                                  typeof item === 'object' &&
                                  'type' in item &&
                                  item.type === 'text' &&
                                  'text' in item ? (
                                    searchQuery?.trim() && typeof item.text === 'string' ? (
                                        <SearchHighlight
                                            string={item.text}
                                            substring={searchQuery}
                                            className="whitespace-pre-wrap"
                                        />
                                    ) : (
                                        <span className="whitespace-pre-wrap">{item.text}</span>
                                    )
                                ) : item &&
                                  typeof item === 'object' &&
                                  'type' in item &&
                                  item.type === 'image' &&
                                  'image' in item &&
                                  typeof item.image === 'string' ? (
                                    <ImageMessageDisplay
                                        message={{
                                            content: {
                                                type: 'image',
                                                image: item.image,
                                            },
                                        }}
                                    />
                                ) : (
                                    <HighlightedJSONViewer
                                        src={item}
                                        name={null}
                                        collapsed={5}
                                        searchQuery={searchQuery}
                                    />
                                )}
                                {index < content.length - 1 && <div className="border-t my-2" />}
                            </React.Fragment>
                        ))}
                    </>
                )
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
                        return (
                            <HighlightedJSONViewer src={parsed} name={null} collapsed={5} searchQuery={searchQuery} />
                        )
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
                    return searchQuery?.trim() ? (
                        <SearchHighlight
                            string={content}
                            substring={searchQuery}
                            className="font-mono whitespace-pre-wrap"
                        />
                    ) : (
                        <span className="font-mono whitespace-pre-wrap">{content}</span>
                    )
                }
            }

            // Fallback: render as plain text.
            const contentStr = typeof content === 'string' ? content : JSON.stringify(content)
            return searchQuery?.trim() ? (
                <SearchHighlight string={contentStr} substring={searchQuery} className="whitespace-pre-wrap" />
            ) : (
                <span className="whitespace-pre-wrap">{contentStr}</span>
            )
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
                    {(content || Object.keys(additionalKwargsEntries).length > 0) && (
                        <>
                            <LemonButton
                                size="small"
                                noPadding
                                icon={show ? <IconEyeHidden /> : <IconEye />}
                                tooltip="Toggle message content"
                                onClick={onToggle}
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
                {show && !!content && <div className="p-2 border-t">{renderMessageContent(content, searchQuery)}</div>}
                {show && Object.keys(additionalKwargsEntries).length > 0 && (
                    <div className="p-2 text-xs border-t">
                        <HighlightedJSONViewer
                            src={additionalKwargsEntries}
                            name={null}
                            collapsed={5}
                            searchQuery={searchQuery}
                        />
                    </div>
                )}
            </div>
        )
    }
)

LLMMessageDisplay.displayName = 'LLMMessageDisplay'
