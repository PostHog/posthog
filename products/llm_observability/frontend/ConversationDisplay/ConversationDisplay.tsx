import { IconMarkdown, IconMarkdownFilled } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { JSONViewer } from 'lib/components/JSONViewer'
import { IconArrowDown, IconArrowUp, IconExclamation } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { lowercaseFirstLetter } from 'lib/utils'
import React, { useState } from 'react'

import { EventType } from '~/types'

interface CompletionMessage {
    /** Almost certainly one of: `user`, `assistant`, `system` */
    role: string
    content: string
    // E.g. tool calls
    [additionalKey: string]: any
}

type AIInput = CompletionMessage[]
type AIOutput = { choices: CompletionMessage[] }

function verifyInputShape(aiInput: any): AIInput | null {
    if (
        Array.isArray(aiInput) &&
        aiInput.every(
            (message: any) =>
                typeof message === 'object' &&
                'role' in message &&
                typeof message.role === 'string' &&
                'content' in message &&
                typeof message.content === 'string'
        )
    ) {
        return aiInput
    }
    return null
}

function verifyOutputShape(aiOutput: any): AIOutput | null {
    if (
        typeof aiOutput === 'object' &&
        'choices' in aiOutput &&
        Array.isArray(aiOutput.choices) &&
        aiOutput.choices.every(
            (message: any) =>
                typeof message === 'object' &&
                'role' in message &&
                typeof message.role === 'string' &&
                'content' in message &&
                typeof message.content === 'string'
        )
    ) {
        return aiOutput
    }
    return null
}

export function ConversationDisplay({ eventProperties }: { eventProperties: EventType['properties'] }): JSX.Element {
    const input = verifyInputShape(eventProperties.$ai_input)
    const output = verifyOutputShape(eventProperties.$ai_output)
    const {
        $ai_input_tokens: inputTokens,
        $ai_output_tokens: outputTokens,
        $ai_total_cost_usd: totalCostUsd,
        $ai_model: model,
        $ai_latency: latency,
        $ai_http_status: httpStatus,
    } = eventProperties

    return (
        <div className="space-y-2">
            <div className="flex flex-wrap gap-x-2">
                {typeof latency === 'number' && (
                    <MetadataTag label="Latency">{`${Math.round(latency * 10e2) / 10e2} s of latency`}</MetadataTag>
                )}
                {typeof inputTokens === 'number' && typeof outputTokens === 'number' && (
                    <MetadataTag label="Token usage">
                        {`${inputTokens} prompt tokens → ${outputTokens} completion tokens (∑ ${
                            inputTokens + outputTokens
                        })`}
                    </MetadataTag>
                )}
                {model && (
                    <MetadataTag label="Model" copyable>
                        {model}
                    </MetadataTag>
                )}
                {typeof totalCostUsd === 'number' && (
                    <MetadataTag label="Total generation cost">
                        {`$${Math.round(totalCostUsd * 10e6) / 10e6}`}
                    </MetadataTag>
                )}
            </div>
            <div className="bg-bg-light rounded-lg border p-2">
                <h4 className="flex items-center gap-x-1.5 text-xs font-semibold mb-2">
                    <IconArrowUp className="text-base" />
                    Input
                </h4>
                {input?.map((message, i) => (
                    <>
                        <MessageDisplay key={i} message={message} />
                        {i < input.length - 1 && <div className="border-l ml-2 h-2" /> /* Spacer connecting messages */}
                    </>
                )) || (
                    <div className="rounded border text-default p-2 italic bg-[var(--background-danger-subtle)]">
                        Missing input
                    </div>
                )}
                <h4 className="flex items-center gap-x-1.5 text-xs font-semibold my-2">
                    <IconArrowDown className="text-base" />
                    Output{output && output.choices.length > 1 ? ' (multiple choices)' : ''}
                </h4>
                {output?.choices.map((message, i) => (
                    <>
                        <MessageDisplay key={i} message={message} isOutput />
                        {i < output.choices.length - 1 && (
                            <div className="border-l ml-4 h-2" /> /* Spacer connecting messages visually */
                        )}
                    </>
                )) || (
                    <div className="flex items-center gap-1.5 rounded border text-default p-2 font-medium bg-[var(--background-danger-subtle)]">
                        <IconExclamation className="text-base" />
                        {httpStatus ? `Generation failed with HTTP status ${httpStatus}` : 'Missing output'}
                    </div>
                )}
            </div>
        </div>
    )
}

function MetadataTag({
    children,
    label,
    copyable = false,
}: {
    children: string
    label: string
    copyable?: boolean
}): JSX.Element {
    let wrappedChildren: React.ReactNode = children
    if (copyable) {
        wrappedChildren = (
            <CopyToClipboardInline iconSize="xsmall" description={lowercaseFirstLetter(label)} tooltipMessage={label}>
                {children}
            </CopyToClipboardInline>
        )
    } else {
        wrappedChildren = <Tooltip title={label}>{children}</Tooltip>
    }

    return <LemonTag className="bg-bg-light cursor-default">{wrappedChildren}</LemonTag>
}

function MessageDisplay({ message, isOutput }: { message: CompletionMessage; isOutput?: boolean }): JSX.Element {
    const [isRenderingMarkdown, setIsRenderingMarkdown] = useState(!!message.content)

    const { role, content, ...additionalKwargs } = message
    const additionalKwargsEntries = Object.entries(additionalKwargs)

    return (
        <div
            className={clsx(
                'rounded border text-default',
                isOutput
                    ? 'bg-[var(--background-success-subtle)]'
                    : role === 'system'
                    ? 'bg-[var(--background-secondary)]'
                    : role === 'user'
                    ? 'bg-bg-light'
                    : 'bg-[var(--blue-50)] dark:bg-[var(--blue-800)]' // We don't have a semantic color using blue
            )}
        >
            <div className="flex items-center gap-1 w-full px-2 h-6 text-xs font-medium">
                <span className="grow">{role}</span>
                {content && (
                    <LemonButton
                        size="small"
                        noPadding
                        icon={isRenderingMarkdown ? <IconMarkdownFilled /> : <IconMarkdown />}
                        tooltip="Toggle Markdown rendering"
                        onClick={() => setIsRenderingMarkdown(!isRenderingMarkdown)}
                    />
                )}
                <CopyToClipboardInline iconSize="small" description="message content" explicitValue={content} />
            </div>
            {!!content && (
                <div className={clsx('p-2 whitespace-pre-wrap border-t', !isRenderingMarkdown && 'font-mono text-xs')}>
                    {isRenderingMarkdown ? <LemonMarkdown>{content}</LemonMarkdown> : content}
                </div>
            )}
            {!!additionalKwargsEntries && additionalKwargsEntries.length > 0 && (
                <div className="p-2 text-xs border-t">
                    {additionalKwargsEntries.map(([key, value]) => {
                        if (key === 'tool_calls' && Array.isArray(value)) {
                            value = value.map((toolCall: any) => {
                                if ('function' in toolCall && toolCall.function && 'arguments' in toolCall.function) {
                                    return {
                                        ...toolCall,
                                        function: {
                                            ...toolCall.function,
                                            arguments: JSON.parse(toolCall.function.arguments),
                                        },
                                    }
                                }
                            })
                        }
                        return (
                            <JSONViewer
                                key={key}
                                name={key}
                                src={value}
                                collapseStringsAfterLength={200}
                                displayDataTypes={false}
                                // shouldCollapse limits depth shown at first. `> 4` is chosen so that we do show
                                // function arguments in `tool_calls`, but if an argument is an object,
                                // its child objects are collapsed by default
                                shouldCollapse={({ namespace }) => namespace.length > 5}
                            />
                        )
                    })}
                </div>
            )}
        </div>
    )
}
