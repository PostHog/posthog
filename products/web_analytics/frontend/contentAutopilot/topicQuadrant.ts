import type { AEOPromptSetTopicCountsApi } from 'products/web_analytics/frontend/generated/api.schemas'

export type TopicQuadrantKey = 'strong' | 'mentioned_not_cited' | 'cited_not_mentioned' | 'weak'

export interface TopicQuadrantPoint {
    topic: string
    mentionRate: number
    citationRate: number
    answers: number
}

export interface TopicQuadrantGroup {
    key: TopicQuadrantKey
    points: TopicQuadrantPoint[]
}

const QUADRANT_ORDER: TopicQuadrantKey[] = ['strong', 'mentioned_not_cited', 'cited_not_mentioned', 'weak']

/** Places each topic against the whole set's rates: above both is strong, below both is weak, and the two mixed
 *  corners say whether the gap is being named or being linked. Topics without answers are left out. */
export function topicQuadrants(
    topics: AEOPromptSetTopicCountsApi[],
    setMentionRate: number,
    setCitationRate: number
): TopicQuadrantGroup[] {
    const groups = new Map<TopicQuadrantKey, TopicQuadrantPoint[]>(QUADRANT_ORDER.map((key) => [key, []]))
    for (const topic of topics) {
        if (topic.mention_rate === null || topic.citation_rate === null) {
            continue
        }
        const mentioned = topic.mention_rate >= setMentionRate
        const cited = topic.citation_rate >= setCitationRate
        const key: TopicQuadrantKey = mentioned
            ? cited
                ? 'strong'
                : 'mentioned_not_cited'
            : cited
              ? 'cited_not_mentioned'
              : 'weak'
        groups.get(key)?.push({
            topic: topic.topic,
            mentionRate: topic.mention_rate,
            citationRate: topic.citation_rate,
            answers: topic.checks - topic.failed,
        })
    }
    return QUADRANT_ORDER.map((key) => ({ key, points: groups.get(key) ?? [] }))
}
