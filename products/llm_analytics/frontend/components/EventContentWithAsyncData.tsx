import React from 'react'

import { HighlightedJSONViewer } from 'lib/components/HighlightedJSONViewer'
import { isObject } from 'lib/utils'

import { ConversationMessagesDisplay } from '../ConversationDisplay/ConversationMessagesDisplay'
import { useAIData } from '../hooks/useAIData'
import { normalizeMessage, normalizeMessages } from '../utils'
import { AIDataLoading } from './AIDataLoading'

interface EventContentGenerationProps {
    eventId: string
<<<<<<< HEAD
    traceId?: string | null
=======
    traceId?: string
>>>>>>> ab34249ab8 (feat(llma): add sentiment UI to traces table and trace detail view)
    rawInput: unknown
    rawOutput: unknown
    tools: unknown
    errorData: unknown
    httpStatus: unknown
    raisedError: boolean
    searchQuery?: string
    displayOption?: 'expand_all' | 'collapse_except_output_and_last_input' | 'text_view'
}

export function EventContentGeneration({
    eventId,
    traceId,
    rawInput,
    rawOutput,
    tools,
    errorData,
    httpStatus,
    raisedError,
    searchQuery,
    displayOption,
}: EventContentGenerationProps): JSX.Element {
    const { input, output, isLoading } = useAIData({
        uuid: eventId,
        input: rawInput,
        output: rawOutput,
    })

    // Map each normalized input message back to its original index in $ai_input.
    // This serves as a stable key for looking up per-message sentiment results,
    // regardless of how normalizeMessage expands/transforms messages.
    const inputSourceIndices = React.useMemo(() => {
        const indices: number[] = []
        if (tools) {
            indices.push(-1) // tools message prepended by normalizeMessages
        }
        if (Array.isArray(input)) {
            for (let i = 0; i < input.length; i++) {
                const expanded = normalizeMessage(input[i], 'user')
                for (let j = 0; j < expanded.length; j++) {
                    indices.push(i)
                }
            }
        }
        return indices
    }, [input, tools])

    if (isLoading) {
        return <AIDataLoading variant="block" />
    }

    return (
        <ConversationMessagesDisplay
            inputNormalized={normalizeMessages(input, 'user', tools)}
            outputNormalized={normalizeMessages(output, 'assistant')}
            inputSourceIndices={inputSourceIndices}
            errorData={errorData}
            httpStatus={typeof httpStatus === 'number' ? httpStatus : undefined}
            raisedError={raisedError}
            searchQuery={searchQuery}
<<<<<<< HEAD
            displayOption={displayOption}
            traceId={traceId}
=======
            traceId={traceId}
            generationEventId={eventId}
>>>>>>> ab34249ab8 (feat(llma): add sentiment UI to traces table and trace detail view)
        />
    )
}

interface EventContentDisplayAsyncProps {
    eventId: string
    rawInput: unknown
    rawOutput: unknown
    raisedError?: boolean
}

export function EventContentDisplayAsync({
    eventId,
    rawInput,
    rawOutput,
    raisedError,
}: EventContentDisplayAsyncProps): JSX.Element {
    const { input, output, isLoading } = useAIData({
        uuid: eventId,
        input: rawInput,
        output: rawOutput,
    })

    if (isLoading) {
        return <AIDataLoading variant="block" />
    }

    return (
        <div className="space-y-4">
            <div>
                <h3 className="font-semibold mb-2">Input</h3>
                <div className="p-2 bg-surface-secondary rounded text-xs overflow-auto">
                    {isObject(input) ? (
                        <HighlightedJSONViewer src={input} name={null} collapsed={5} />
                    ) : (
                        <span className="font-mono">{JSON.stringify(input ?? null)}</span>
                    )}
                </div>
            </div>
            <div>
                <h3 className="font-semibold mb-2">Output</h3>
                <div
                    className={`p-2 rounded text-xs overflow-auto ${
                        raisedError ? 'bg-danger-highlight' : 'bg-surface-secondary'
                    }`}
                >
                    {isObject(output) ? (
                        <HighlightedJSONViewer src={output} name={null} collapsed={5} />
                    ) : (
                        <span className="font-mono">{JSON.stringify(output ?? null)}</span>
                    )}
                </div>
            </div>
        </div>
    )
}
