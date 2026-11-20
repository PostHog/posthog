import type { AEOPromptSetTopicCountsApi } from '../generated/api.schemas'
import { topicQuadrants } from './topicQuadrant'

const topic = (name: string, mention: number | null, citation: number | null): AEOPromptSetTopicCountsApi => ({
    topic: name,
    mention_rate: mention,
    citation_rate: citation,
    checks: 12,
    failed: 2,
    cited: 0,
    mentioned: 0,
    prompts: 3,
    active_prompts: 3,
    prompts_cited: 0,
    avg_position: null,
})

describe('topicQuadrants', () => {
    it('places each topic against the set rates, counting a topic at the rate as above it, and skips topics without answers', () => {
        const groups = topicQuadrants(
            [
                topic('Replay', 0.8, 0.6),
                topic('Flags', 0.7, 0.1),
                topic('Surveys', 0.2, 0.5),
                topic('Logs', 0.1, 0.05),
                topic('Exactly average', 0.5, 0.4),
                topic('No answers', null, null),
            ],
            0.5,
            0.4
        )

        expect(groups.map(({ key, points }) => [key, points.map((point) => point.topic)])).toEqual([
            ['strong', ['Replay', 'Exactly average']],
            ['mentioned_not_cited', ['Flags']],
            ['cited_not_mentioned', ['Surveys']],
            ['weak', ['Logs']],
        ])
        expect(groups[0].points[0].answers).toBe(10)
    })
})
