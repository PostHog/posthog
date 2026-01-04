import { IconCheck, IconMinus, IconX } from '@posthog/icons'
import { LemonTag, Link } from '@posthog/lemon-ui'

import { lowercaseFirstLetter } from 'lib/utils'
import { urls } from 'scenes/urls'

import { EventType } from '~/types'

import { MetadataTag } from '../components/MetadataTag'

export function EvaluationDisplay({ eventProperties }: { eventProperties: EventType['properties'] }): JSX.Element {
    const rawResult = eventProperties.$ai_evaluation_result
    const rawApplicable = eventProperties.$ai_evaluation_applicable
    // Check if result is explicitly true (handles both boolean and string 'true')
    const isPass = rawResult === true || rawResult === 'true'
    // N/A when backend explicitly sets applicable to false
    const isNA = rawApplicable === false
    const reasoning = eventProperties.$ai_evaluation_reasoning
    const evaluationName = eventProperties.$ai_evaluation_name
    const model = eventProperties.$ai_evaluation_model
    const traceId = eventProperties.$ai_trace_id
    const targetEventId = eventProperties.$ai_target_event_id

    const renderResultTag = (): JSX.Element => {
        if (isNA) {
            return (
                <LemonTag type="muted" icon={<IconMinus />}>
                    N/A
                </LemonTag>
            )
        }
        if (isPass) {
            return (
                <LemonTag type="success" icon={<IconCheck />}>
                    True
                </LemonTag>
            )
        }
        return (
            <LemonTag type="danger" icon={<IconX />}>
                False
            </LemonTag>
        )
    }

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap gap-2">
                {renderResultTag()}
                {evaluationName && (
                    <MetadataTag label="Evaluation" textToCopy={evaluationName}>
                        {evaluationName}
                    </MetadataTag>
                )}
                {model && (
                    <MetadataTag label="Judge model" textToCopy={lowercaseFirstLetter(model)}>
                        {lowercaseFirstLetter(model)}
                    </MetadataTag>
                )}
                {traceId && targetEventId && (
                    <MetadataTag label="Target event">
                        <Link to={urls.llmAnalyticsTrace(traceId, { event: targetEventId })}>
                            {targetEventId.slice(0, 12)}...
                        </Link>
                    </MetadataTag>
                )}
            </div>

            {reasoning && (
                <div className="p-3 border rounded bg-surface-primary">
                    <div className="font-medium text-xs text-muted mb-1.5">REASONING</div>
                    <div className="text-sm whitespace-pre-wrap">{reasoning}</div>
                </div>
            )}
        </div>
    )
}
