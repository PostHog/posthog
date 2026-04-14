import { LemonTag, Link } from '@posthog/lemon-ui'

import { lowercaseFirstLetter } from 'lib/utils'
import { urls } from 'scenes/urls'

import { EventType } from '~/types'

import { MetadataTag } from '../components/MetadataTag'

export function TagDisplay({ eventProperties }: { eventProperties: EventType['properties'] }): JSX.Element {
    const tags: string[] = eventProperties.$ai_tags ?? []
    const reasoning = eventProperties.$ai_tag_reasoning
    const taggerName = eventProperties.$ai_tagger_name
    const model = eventProperties.$ai_model
    const traceId = eventProperties.$ai_trace_id
    const targetEventId = eventProperties.$ai_target_event_id
    const tagCount = eventProperties.$ai_tag_count ?? tags.length

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap gap-2">
                {tags.length > 0 ? (
                    tags.map((tag: string) => (
                        <LemonTag key={tag} type="highlight">
                            {tag}
                        </LemonTag>
                    ))
                ) : (
                    <LemonTag type="muted">No tags</LemonTag>
                )}
            </div>

            <div className="flex flex-wrap gap-2">
                {taggerName && (
                    <MetadataTag label="Tagger" textToCopy={taggerName}>
                        {taggerName}
                    </MetadataTag>
                )}
                {model && (
                    <MetadataTag label="Model" textToCopy={lowercaseFirstLetter(model)}>
                        {lowercaseFirstLetter(model)}
                    </MetadataTag>
                )}
                <MetadataTag label="Tag count">{String(tagCount)}</MetadataTag>
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
