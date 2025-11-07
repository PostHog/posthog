import { Link } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { QueryContextColumn } from '~/queries/types'

import { LLMMessageDisplay } from './ConversationDisplay/ConversationMessagesDisplay'
import { CompatMessage } from './types'
import { normalizeMessages } from './utils'

const truncateValue = (value: string): string => {
    if (value.length > 8) {
        return `${value.substring(0, 4)}...${value.substring(value.length - 4)}`
    }
    return value
}

export const llmAnalyticsColumnRenderers: Record<string, QueryContextColumn> = {
    'properties.$ai_input[-1]': {
        title: 'Input',
        render: ({ value }) => {
            let inputNormalized: CompatMessage[] | undefined
            try {
                const parsed = typeof value === 'string' ? JSON.parse(value) : value
                inputNormalized = normalizeMessages(parsed, 'user')
            } catch (e) {
                console.warn('Error normalizing properties.$ai_input[-1]', e)
            }
            if (!inputNormalized?.length) {
                return <>–</>
            }
            return <LLMMessageDisplay message={inputNormalized.at(-1)!} isOutput={false} minimal />
        },
    },
    'properties.$ai_input': {
        title: 'Input (full)',
        render: ({ value }) => {
            let inputNormalized: CompatMessage[] | undefined
            try {
                const parsed = typeof value === 'string' ? JSON.parse(value) : value
                inputNormalized = normalizeMessages(parsed, 'user')
            } catch (e) {
                console.warn('Error normalizing properties.$ai_input', e)
            }
            if (!inputNormalized?.length) {
                return <>–</>
            }
            // Show last message
            return <LLMMessageDisplay message={inputNormalized.at(-1)!} isOutput={false} minimal />
        },
    },
    'properties.$ai_output_choices': {
        title: 'Output',
        render: ({ value }) => {
            let outputNormalized: CompatMessage[] | undefined
            try {
                const parsed = typeof value === 'string' ? JSON.parse(value) : value
                outputNormalized = normalizeMessages(parsed, 'assistant')
            } catch (e) {
                console.warn('Error normalizing properties.$ai_output_choices', e)
            }
            if (!outputNormalized?.length) {
                return <>–</>
            }

            return (
                <div>
                    {outputNormalized.map((message, index) => (
                        <LLMMessageDisplay key={index} message={message} isOutput={true} minimal />
                    ))}
                </div>
            )
        },
    },
    'properties.$ai_trace_id': {
        title: 'Trace ID',
        render: ({ value }) => {
            if (!value || typeof value !== 'string') {
                return null
            }

            const visualValue = truncateValue(value)

            return (
                <Tooltip title={value}>
                    <Link to={`/llm-analytics/traces/${value}`} data-attr="generation-trace-link">
                        {visualValue}
                    </Link>
                </Tooltip>
            )
        },
    },
}
