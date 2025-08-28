import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React from 'react'

import { IconCode, IconEye, IconMarkdown, IconMarkdownFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { HighlightedJSONViewer } from 'lib/components/HighlightedJSONViewer'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { IconExclamation, IconEyeHidden } from 'lib/lemon-ui/icons'
import { isObject } from 'lib/utils'

import { LLMInputOutput } from '../LLMInputOutput'
import { SearchHighlight } from '../SearchHighlight'
import { llmAnalyticsTraceLogic } from '../llmAnalyticsTraceLogic'
import { containsSearchQuery } from '../searchUtils'
import { CompatMessage, VercelSDKImageMessage } from '../types'
import { looksLikeXml } from '../utils'
import { HighlightedLemonMarkdown } from './HighlightedLemonMarkdown'
import { HighlightedXMLViewer } from './HighlightedXMLViewer'
import { XMLViewer } from './XMLViewer'

export function ConversationMessagesDisplay({
    inputNormalized,
    outputNormalized,
    errorData,
    httpStatus,
    raisedError,
    bordered = false,
    searchQuery,
}: {
    inputNormalized: CompatMessage[]
    outputNormalized: CompatMessage[]
    errorData: any
    httpStatus?: number
    raisedError?: boolean
    bordered?: boolean
    searchQuery?: string
}): JSX.Element {
    const {
        inputMessageShowStates,
        outputMessageShowStates,
        searchQuery: currentSearchQuery,
        displayOption,
    } = useValues(llmAnalyticsTraceLogic)
    const { initializeMessageStates, toggleMessage, showAllMessages, hideAllMessages, applySearchResults } =
        useActions(llmAnalyticsTraceLogic)

    // Initialize message states when component mounts or messages change or display option changes
    React.useEffect(() => {
        initializeMessageStates(inputNormalized.length, outputNormalized.length)
    }, [inputNormalized.length, outputNormalized.length, displayOption, initializeMessageStates])

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

    const allInputsExpanded = inputMessageShowStates.every(Boolean)
    const allInputsCollapsed = inputMessageShowStates.every((state: boolean) => !state)

    const inputButtons =
        inputNormalized.length > 0 ? (
            <div className="flex items-center gap-1">
                <LemonButton
                    size="xsmall"
                    onClick={() => showAllMessages('input')}
                    icon={<IconEye />}
                    disabledReason={allInputsExpanded ? 'All inputs are already expanded' : undefined}
                >
                    Expand all
                </LemonButton>
                <LemonButton
                    size="xsmall"
                    onClick={() => hideAllMessages('input')}
                    icon={<IconEyeHidden />}
                    disabledReason={allInputsCollapsed ? 'All inputs are already collapsed' : undefined}
                >
                    Collapse all
                </LemonButton>
            </div>
        ) : undefined

    const allOutputsExpanded = outputMessageShowStates.every(Boolean)
    const allOutputsCollapsed = outputMessageShowStates.every((state: boolean) => !state)

    const outputButtons =
        outputNormalized.length > 0 ? (
            <div className="flex items-center gap-1">
                <LemonButton
                    size="xsmall"
                    onClick={() => showAllMessages('output')}
                    icon={<IconEye />}
                    disabledReason={allOutputsExpanded ? 'All outputs are already expanded' : undefined}
                >
                    Expand all
                </LemonButton>
                <LemonButton
                    size="xsmall"
                    onClick={() => hideAllMessages('output')}
                    icon={<IconEyeHidden />}
                    disabledReason={allOutputsCollapsed ? 'All outputs are already collapsed' : undefined}
                >
                    Collapse all
                </LemonButton>
            </div>
        ) : undefined

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

    const showOutputSection = outputNormalized.length > 0 || !raisedError

    return (
        <>
            <LLMInputOutput
                inputDisplay={inputDisplay}
                outputDisplay={
                    showOutputSection ? (
                        outputNormalized.length > 0 ? (
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
                            <div className="rounded border text-default p-2 italic bg-[var(--bg-fill-error-tertiary)]">
                                No output
                            </div>
                        )
                    ) : null
                }
                outputHeading={showOutputSection ? 'Output' : undefined}
                bordered={bordered}
                inputButtons={inputButtons}
                outputButtons={showOutputSection ? outputButtons : undefined}
            />
            {raisedError && errorData && (
                <div className="mt-4">
                    <h4 className="flex items-center justify-between text-xs font-semibold mb-2">
                        <div className="flex items-center gap-x-1.5">
                            <IconExclamation className="text-base text-danger" />
                            Error {httpStatus ? `(${httpStatus})` : ''}
                        </div>
                    </h4>
                    <div className="flex items-center gap-1.5 rounded border text-default p-2 font-medium bg-[var(--bg-fill-error-tertiary)] border-danger overflow-x-auto">
                        {isObject(errorData) ? (
                            <HighlightedJSONViewer src={errorData} collapsed={4} searchQuery={searchQuery} />
                        ) : (
                            <span className="font-mono">
                                {(() => {
                                    try {
                                        const parsedJson = JSON.parse(errorData)
                                        return isObject(parsedJson) ? (
                                            <HighlightedJSONViewer
                                                src={parsedJson}
                                                collapsed={5}
                                                searchQuery={searchQuery}
                                            />
                                        ) : (
                                            JSON.stringify(errorData ?? null)
                                        )
                                    } catch {
                                        return JSON.stringify(errorData ?? null)
                                    }
                                })()}
                            </span>
                        )}
                    </div>
                </div>
            )}
        </>
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
        show = true,
        minimal = false,
        onToggle,
        searchQuery,
    }: {
        message: CompatMessage
        isOutput?: boolean
        /** @default true */
        show?: boolean
        /** In minimal mode, we don't show the role, toggles, or additional kwargs, and reduce padding. */
        minimal?: boolean
        onToggle?: () => void
        searchQuery?: string
    }): JSX.Element => {
        const { role, content, ...additionalKwargs } = message
        let { isRenderingMarkdown, isRenderingXml } = useValues(llmAnalyticsTraceLogic)
        const { toggleMarkdownRendering, toggleXmlRendering } = useActions(llmAnalyticsTraceLogic)

        if (minimal) {
            isRenderingMarkdown = true
            isRenderingXml = false
        }

        // Compute whether the content looks like Markdown.
        // (Heuristic: looks for code blocks, blockquotes, headings, italic, bold, underline, strikethrough)
        const isMarkdownCandidate =
            content && typeof content === 'string' ? /(\n\s*```|^>\s|#{1,6}\s|_|\*|~~)/.test(content) : false

        // Compute whether the content looks like XML
        const isXmlCandidate = looksLikeXml(content)

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
                    if (parsed.type === 'output_text' && parsed.text) {
                        return <span className="whitespace-pre-wrap">{parsed.text}</span>
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

            // If the content appears to be XML, render based on the toggle.
            if (isXmlCandidate && typeof content === 'string') {
                if (isRenderingXml) {
                    return searchQuery?.trim() ? (
                        <HighlightedXMLViewer collapsed={3} searchQuery={searchQuery}>
                            {content}
                        </HighlightedXMLViewer>
                    ) : (
                        <XMLViewer collapsed={3}>{content}</XMLViewer>
                    )
                }
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
                            return searchQuery?.trim() ? (
                                <HighlightedLemonMarkdown className="whitespace-pre-wrap" searchQuery={searchQuery}>
                                    {escapedContent}
                                </HighlightedLemonMarkdown>
                            ) : (
                                <LemonMarkdown className="whitespace-pre-wrap">{escapedContent}</LemonMarkdown>
                            )
                        } catch {
                            // If markdown still fails, fall back to plain text
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
                    } else {
                        // pre-wrap, because especially in system prompts, we want to preserve newlines even if they aren't fully Markdown-style
                        return searchQuery?.trim() ? (
                            <HighlightedLemonMarkdown className="whitespace-pre-wrap" searchQuery={searchQuery}>
                                {content}
                            </HighlightedLemonMarkdown>
                        ) : (
                            <LemonMarkdown className="whitespace-pre-wrap">{content}</LemonMarkdown>
                        )
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
                    'border text-default min-w-[min(fit-content,8rem)]',
                    !minimal ? 'rounded' : 'rounded-sm text-xs max-w-50 max-h-50 overflow-y-auto',
                    isOutput
                        ? 'bg-[var(--color-bg-fill-success-tertiary)] not-last:mb-2'
                        : role === 'user'
                          ? 'bg-[var(--color-bg-fill-tertiary)]'
                          : role === 'assistant'
                            ? 'bg-[var(--color-bg-fill-info-tertiary)]'
                            : null
                )}
            >
                {!minimal && (
                    <div
                        className={clsx(
                            'flex items-center gap-1 w-full px-2 h-6 text-xs font-medium select-none',
                            onToggle && 'cursor-pointer'
                        )}
                        onClick={(e) => {
                            const clickedButton = (e.target as Element).closest('button')
                            if (!clickedButton) {
                                onToggle?.()
                            }
                        }}
                    >
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
                                {isXmlCandidate && role !== 'tool' && role !== 'tools' && (
                                    <LemonButton
                                        size="small"
                                        noPadding
                                        icon={<IconCode />}
                                        tooltip="Toggle XML syntax highlighting"
                                        onClick={toggleXmlRendering}
                                        active={isRenderingXml}
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
                )}
                {show && !!content && (
                    <div className={!minimal ? 'p-2 border-t' : 'p-1'}>
                        {renderMessageContent(content, searchQuery)}
                    </div>
                )}
                {show && !minimal && Object.keys(additionalKwargsEntries).length > 0 && (
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
