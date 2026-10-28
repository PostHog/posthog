import type { MCPIntentMapPoint, MCPIntentMapTopic } from '~/queries/schema/schema-general'

import {
    MAX_BUBBLE_RADIUS,
    MIN_BUBBLE_RADIUS,
    OUTLIER_COLOR,
    UNASSIGNED_COLOR,
    assignTopicColorSlots,
    bubbleRadius,
    buildPointSeries,
    buildTopicSeries,
    topicColor,
} from './intentScatter'

const topics: MCPIntentMapTopic[] = [
    { topic_id: 'a', label: 'Create insights', summary: '', x: 1, y: 0, calls: 400, share_pct: 80 },
    { topic_id: 'b', label: 'List flags', summary: '', x: 0, y: 1, calls: 100, share_pct: 20 },
]
const slots = assignTopicColorSlots({}, topics)

function point(overrides: Partial<MCPIntentMapPoint>): MCPIntentMapPoint {
    return {
        intent_hash: 'h',
        intent_text: 'text',
        x: 0,
        y: 0,
        topic_id: 'a',
        is_outlier: false,
        calls: 1,
        tool: 'query-trends',
        ...overrides,
    }
}

describe('bubbleRadius', () => {
    it('grows with the square root of calls and stays within bounds', () => {
        expect(bubbleRadius(0, 400)).toBe(MIN_BUBBLE_RADIUS)
        expect(bubbleRadius(400, 400)).toBe(MAX_BUBBLE_RADIUS)
        expect(bubbleRadius(100, 400)).toBe(MIN_BUBBLE_RADIUS + (MAX_BUBBLE_RADIUS - MIN_BUBBLE_RADIUS) * 0.5)
        expect(bubbleRadius(800, 400)).toBe(MAX_BUBBLE_RADIUS)
    })
})

describe('buildTopicSeries', () => {
    it('makes one bubble per topic, sized by calls, with topic meta', () => {
        const series = buildTopicSeries(topics, slots)

        expect(series.map((s) => s.key)).toEqual(['topic-a', 'topic-b'])
        expect(series[0].points[0].radius).toBe(MAX_BUBBLE_RADIUS)
        expect(series[1].points[0].radius).toBe(MIN_BUBBLE_RADIUS + (MAX_BUBBLE_RADIUS - MIN_BUBBLE_RADIUS) * 0.5)
        expect(series[0].points[0].meta).toEqual({
            kind: 'topic',
            topicId: 'a',
            label: 'Create insights',
            calls: 400,
            sharePct: 80,
        })
        expect(series[0].color).toBe(topicColor('a', slots))
    })
})

describe('buildPointSeries', () => {
    it('groups points by topic, keeps outliers as crosses and unknown topics as grey', () => {
        const series = buildPointSeries(
            [
                point({ intent_hash: '1', topic_id: 'a' }),
                point({ intent_hash: '2', topic_id: 'a' }),
                point({ intent_hash: '3', topic_id: 'b', is_outlier: true }),
                point({ intent_hash: '4', topic_id: null }),
                point({ intent_hash: '5', topic_id: 'archived' }),
            ],
            topics,
            slots
        )

        expect(series.map((s) => [s.key, s.points.length, s.shape])).toEqual([
            ['points-a', 2, 'circle'],
            ['points-unassigned', 2, 'circle'],
            ['points-outliers', 1, 'cross'],
        ])
        expect(series[1].color).toBe(UNASSIGNED_COLOR)
        expect(series[2].color).toBe(OUTLIER_COLOR)
        expect(series[0].color).toBe(buildTopicSeries(topics, slots)[0].color)
        expect(series[2].points[0].meta).toMatchObject({
            kind: 'intent',
            intentHash: '3',
            isOutlier: true,
            tool: 'query-trends',
        })
    })

    it('returns nothing for no points', () => {
        expect(buildPointSeries([], topics, slots)).toEqual([])
    })
})
