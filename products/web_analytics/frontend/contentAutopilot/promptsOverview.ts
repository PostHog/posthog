import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type {
    AEOPromptSetCountsApi,
    AEOPromptSetOverviewApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import { type KpiCardContent, countDelta, pointsDelta, positionDelta, positionLabel } from './promptReport'
import { sortEngines } from './utils'

export interface PromptsOverviewKpis {
    promptsTracked: KpiCardContent
    checks: KpiCardContent
    mentionRate: KpiCardContent
    citationRate: KpiCardContent
    position: KpiCardContent
}

const answered = (counts: AEOPromptSetCountsApi): number => counts.checks - counts.failed

const rateCard = (
    overview: AEOPromptSetOverviewApi,
    rate: 'mention_rate' | 'citation_rate',
    count: 'mentioned' | 'cited'
): KpiCardContent => {
    const { current, previous, days } = overview
    const value = current[rate]
    const before = previous[rate]
    return {
        value: value === null ? 'No answers' : percentage(value, 0),
        note:
            value === null
                ? 'No answers in this date range'
                : `${humanFriendlyNumber(current[count])} of ${pluralize(answered(current), 'answer')}`,
        delta:
            value === null || before === null
                ? null
                : pointsDelta(value - before, `Against the ${days} days before, in percentage points`),
    }
}

const citedPromptsNote = (counts: AEOPromptSetCountsApi): string => {
    if (counts.prompts === 0) {
        return 'None ran in this date range'
    }
    const cited =
        counts.prompts_cited === counts.prompts
            ? 'all of them'
            : counts.prompts_cited === 0
              ? 'none of them'
              : `${counts.prompts_cited} of them`
    return `${counts.prompts} ran in this date range, ${cited} cited`
}

const positionCard = ({ current, previous, days }: AEOPromptSetOverviewApi): KpiCardContent => {
    const value = current.avg_position
    const before = previous.avg_position
    return {
        value: value == null ? 'Not cited' : positionLabel(value),
        note:
            value == null ? 'No cited answers in this date range' : `Over ${pluralize(current.cited, 'cited answer')}`,
        delta:
            value == null || before == null
                ? null
                : positionDelta(value - before, `Against the ${days} days before. Lower is better`),
    }
}

/** The numbers at the top of the prompts tab, each against the window before. */
export const promptsOverviewKpis = (overview: AEOPromptSetOverviewApi): PromptsOverviewKpis => {
    const { current, previous, days } = overview
    return {
        promptsTracked: {
            value: humanFriendlyNumber(overview.prompts_tracked),
            note: citedPromptsNote(current),
            delta: null,
        },
        checks: {
            value: humanFriendlyNumber(current.checks),
            note: current.failed === 0 ? 'All answered' : `${pluralize(current.failed, 'check')} failed`,
            delta:
                previous.checks === 0
                    ? null
                    : countDelta(current.checks - previous.checks, `Against the ${days} days before`),
        },
        mentionRate: rateCard(overview, 'mention_rate', 'mentioned'),
        citationRate: rateCard(overview, 'citation_rate', 'cited'),
        position: positionCard(overview),
    }
}

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
