import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { AEOPromptSetOverviewApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { positionLabel } from './promptReport'
import { formatShare } from './shares'
import { sortEngines } from './utils'

/** Without a single check in either window, the overview has nothing to show. */
export const promptsOverviewHasChecks = (overview: AEOPromptSetOverviewApi): boolean =>
    overview.current.checks > 0 || overview.previous.checks > 0

/** The fill steps of the heatmap, so a rate maps to one of a few shades a person can tell apart. */
export const ENGINE_TOPIC_HEAT_STEPS = 5

export interface EngineTopicCell {
    engine: string
    /** Null when the engine gave no answer for the topic, which is not the same as a rate of zero. */
    rate: number | null
    answers: number
    mentioned: number
    /** 0 for the lowest rates up to `ENGINE_TOPIC_HEAT_STEPS - 1` for the highest. Null without a rate. */
    heat: number | null
}

export interface EngineTopicRow {
    topic: string
    cells: EngineTopicCell[]
}

export interface EngineTopicGrid {
    engines: string[]
    rows: EngineTopicRow[]
}

/** One row per topic and one cell per engine that answered, with the engines in the order the chart uses. */
export const engineTopicGrid = ({
    topics,
    engine_topics: pairs,
}: Pick<AEOPromptSetOverviewApi, 'topics' | 'engine_topics'>): EngineTopicGrid => {
    const engines = sortEngines(pairs.map(({ engine }) => engine))
    const byPair = new Map(pairs.map((pair) => [JSON.stringify([pair.engine, pair.topic]), pair]))
    // Prompts without a topic go last, because their row is the rest and not a topic to compare.
    const names = topics.map(({ topic }) => topic).sort((a, b) => Number(!a) - Number(!b))
    return {
        engines,
        rows: names.map((topic) => ({
            topic,
            cells: engines.map((engine) => {
                const pair = byPair.get(JSON.stringify([engine, topic]))
                return pair
                    ? {
                          engine,
                          rate: pair.mention_rate,
                          answers: pair.answers,
                          mentioned: pair.mentioned,
                          heat: Math.min(
                              ENGINE_TOPIC_HEAT_STEPS - 1,
                              Math.floor(pair.mention_rate * ENGINE_TOPIC_HEAT_STEPS)
                          ),
                      }
                    : { engine, rate: null, answers: 0, mentioned: 0, heat: null }
            }),
        })),
    }
}

export type OverviewTileKey = 'prompts' | 'visibility' | 'cited' | 'position'

/** The overview's headline numbers. Each tile shows only its value: bases and changes stay in the tables below. */
export const overviewTiles = (overview: AEOPromptSetOverviewApi): Record<OverviewTileKey, string> => {
    const { current } = overview
    const answered = current.checks - current.failed
    const share = (part: number): string => (answered > 0 ? formatShare(part / answered) : '-')
    return {
        prompts: humanFriendlyNumber(overview.prompts_tracked),
        visibility: share(current.mentioned),
        cited: share(current.cited),
        position: current.avg_position === null ? 'Not cited' : positionLabel(current.avg_position),
    }
}
