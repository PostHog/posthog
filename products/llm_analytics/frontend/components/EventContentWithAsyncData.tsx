import { HighlightedJSONViewer } from 'lib/components/HighlightedJSONViewer'
import { isObject } from 'lib/utils'

import { ConversationMessagesDisplay } from '../ConversationDisplay/ConversationMessagesDisplay'
import { useAIData } from '../hooks/useAIData'
import { normalizeMessages } from '../utils'
import { AIDataLoading } from './AIDataLoading'

interface EventContentGenerationProps {
    eventId: string
    rawInput: unknown
    rawOutput: unknown
    tools: unknown
    errorData: unknown
    httpStatus: unknown
    raisedError: boolean
    searchQuery?: string
}

export function EventContentGeneration({
    eventId,
    rawInput,
    rawOutput,
    tools,
    errorData,
    httpStatus,
    raisedError,
    searchQuery,
}: EventContentGenerationProps): JSX.Element {
    const { input, output, isLoading } = useAIData({
        uuid: eventId,
        input: rawInput,
        output: rawOutput,
    })

    if (isLoading) {
        return <AIDataLoading variant="block" />
    }

    return (
        <ConversationMessagesDisplay
            inputNormalized={normalizeMessages(input, 'user', tools)}
            outputNormalized={normalizeMessages(output, 'assistant')}
            errorData={errorData}
            httpStatus={typeof httpStatus === 'number' ? httpStatus : undefined}
            raisedError={raisedError}
            searchQuery={searchQuery}
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
