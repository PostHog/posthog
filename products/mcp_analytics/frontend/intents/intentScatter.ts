import type { ScatterSeries } from '@posthog/quill-charts'

import { getSeriesColor } from 'lib/colors'

import type { MCPIntentMapPoint, MCPIntentMapTopic } from '~/queries/schema/schema-general'

export const OUTLIER_COLOR = '#888888'
export const UNASSIGNED_COLOR = '#b0b0b0'
export const MIN_BUBBLE_RADIUS = 6
export const MAX_BUBBLE_RADIUS = 28
export const POINT_RADIUS = 4

/** Per-point data carried through quill's scatter `meta`, handed back on hover and click. */
export interface IntentScatterMeta {
    kind: 'topic' | 'intent'
    topicId: string | null
    label: string
    calls: number
    intentHash?: string
    tool?: string
    isOutlier?: boolean
    sharePct?: number
}

export type IntentScatterSeries = ScatterSeries<IntentScatterMeta>

/** Bubble area tracks calls, so the radius grows with the square root. */
export function bubbleRadius(
    calls: number,
    maxCalls: number,
    min: number = MIN_BUBBLE_RADIUS,
    max: number = MAX_BUBBLE_RADIUS
): number {
    if (maxCalls <= 0 || calls <= 0) {
        return min
    }
    return min + (max - min) * Math.sqrt(Math.min(calls, maxCalls) / maxCalls)
}

export type TopicColorSlots = Record<string, number>

/** Gives each topic not seen before the next palette slot, so filtering or re-ranking never swaps colors. */
export function assignTopicColorSlots(slots: TopicColorSlots, topics: MCPIntentMapTopic[]): TopicColorSlots {
    const unseen = topics.filter((topic) => !(topic.topic_id in slots))
    if (unseen.length === 0) {
        return slots
    }
    const next = { ...slots }
    let slot = Object.keys(slots).length
    for (const topic of unseen) {
        next[topic.topic_id] = slot++
    }
    return next
}

export function topicColor(topicId: string | null, slots: TopicColorSlots): string {
    if (topicId === null || !(topicId in slots)) {
        return UNASSIGNED_COLOR
    }
    return getSeriesColor(slots[topicId])
}

export function buildTopicSeries(topics: MCPIntentMapTopic[], slots: TopicColorSlots): IntentScatterSeries[] {
    const maxCalls = Math.max(0, ...topics.map((topic) => topic.calls))
    return topics.map((topic) => ({
        key: `topic-${topic.topic_id}`,
        label: topic.label,
        color: topicColor(topic.topic_id, slots),
        shape: 'circle',
        points: [
            {
                x: topic.x,
                y: topic.y,
                radius: bubbleRadius(topic.calls, maxCalls),
                meta: {
                    kind: 'topic' as const,
                    topicId: topic.topic_id,
                    label: topic.label,
                    calls: topic.calls,
                    sharePct: topic.share_pct,
                },
            },
        ],
    }))
}

/** One series per topic for assigned points, one grey series for unassigned, one cross series for outliers. */
export function buildPointSeries(
    points: MCPIntentMapPoint[],
    topics: MCPIntentMapTopic[],
    slots: TopicColorSlots
): IntentScatterSeries[] {
    const labels = new Map(topics.map((topic) => [topic.topic_id, topic.label]))
    const byTopic = new Map<string | null, MCPIntentMapPoint[]>()
    const outliers: MCPIntentMapPoint[] = []
    for (const point of points) {
        if (point.is_outlier) {
            outliers.push(point)
            continue
        }
        const bucket = byTopic.get(point.topic_id) ?? []
        bucket.push(point)
        byTopic.set(point.topic_id, bucket)
    }

    const toPoint = (point: MCPIntentMapPoint): IntentScatterSeries['points'][number] => ({
        x: point.x,
        y: point.y,
        meta: {
            kind: 'intent' as const,
            topicId: point.topic_id,
            label: point.intent_text,
            calls: point.calls,
            intentHash: point.intent_hash,
            tool: point.tool,
            isOutlier: point.is_outlier,
        },
    })

    const series: IntentScatterSeries[] = []
    for (const topic of topics) {
        const bucket = byTopic.get(topic.topic_id)
        if (bucket?.length) {
            series.push({
                key: `points-${topic.topic_id}`,
                label: topic.label,
                color: topicColor(topic.topic_id, slots),
                pointRadius: POINT_RADIUS,
                shape: 'circle',
                points: bucket.map(toPoint),
            })
        }
    }
    const unassigned = [...byTopic.entries()].filter(([topicId]) => topicId === null || !labels.has(topicId))
    const unassignedPoints = unassigned.flatMap(([, bucket]) => bucket)
    if (unassignedPoints.length) {
        series.push({
            key: 'points-unassigned',
            label: 'No topic',
            color: UNASSIGNED_COLOR,
            pointRadius: POINT_RADIUS,
            shape: 'circle',
            points: unassignedPoints.map(toPoint),
        })
    }
    if (outliers.length) {
        series.push({
            key: 'points-outliers',
            label: 'Outliers',
            color: OUTLIER_COLOR,
            pointRadius: POINT_RADIUS,
            shape: 'cross',
            points: outliers.map(toPoint),
        })
    }
    return series
}
