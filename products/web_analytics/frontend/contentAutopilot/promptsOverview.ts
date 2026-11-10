import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type {
    AEOPromptSetCountsApi,
    AEOPromptSetModeComparisonApi,
    AEOPromptSetOverviewApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import {
    type KpiCardContent,
    type KpiDelta,
    countDelta,
    pointsDelta,
    positionDelta,
    positionLabel,
} from './promptReport'
import { engineLabel, sortEngines } from './utils'

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
                ? `No answers in the last ${days} days`
                : `${humanFriendlyNumber(current[count])} of ${pluralize(answered(current), 'answer')}`,
        delta:
            value === null || before === null
                ? null
                : pointsDelta(value - before, `Against the ${days} days before, in percentage points`),
    }
}

const citedPromptsNote = (counts: AEOPromptSetCountsApi, days: number): string => {
    if (counts.prompts === 0) {
        return `None ran in the last ${days} days`
    }
    const cited =
        counts.prompts_cited === counts.prompts
            ? 'all of them'
            : counts.prompts_cited === 0
              ? 'none of them'
              : `${counts.prompts_cited} of them`
    return `${counts.prompts} ran in the last ${days} days, ${cited} cited`
}

const positionCard = ({ current, previous, days }: AEOPromptSetOverviewApi): KpiCardContent => {
    const value = current.avg_position
    const before = previous.avg_position
    return {
        value: value == null ? 'Not cited' : positionLabel(value),
        note:
            value == null
                ? `No cited answers in the last ${days} days`
                : `Over ${pluralize(current.cited, 'cited answer')}`,
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
            note: citedPromptsNote(current, days),
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

export interface MemoryVsSearchRow {
    engine: string
    label: string
    memoryRate: string | null
    searchRate: string | null
    /** "Without searching, Claude mentions you in 31% of answers; with search, 47%." */
    summary: string
    gap: KpiDelta | null
    note: string
}

const memoryVsSearchRow = (row: AEOPromptSetModeComparisonApi): MemoryVsSearchRow => {
    const label = engineLabel(row.engine)
    const memory = row.no_search_mention_rate
    const search = row.web_search_mention_rate
    const memoryRate = memory === null ? null : percentage(memory, 0)
    const searchRate = search === null ? null : percentage(search, 0)
    const withoutSearch = `Without searching, ${label} mentions you in ${memoryRate ?? '0%'} of answers`
    return {
        engine: row.engine,
        label,
        memoryRate,
        searchRate,
        summary:
            searchRate === null
                ? `${withoutSearch}. It has no answers with search for the same prompts yet.`
                : `${withoutSearch}; with search, ${searchRate}.`,
        gap:
            memory === null || search === null
                ? null
                : pointsDelta(search - memory, 'Mention rate with search minus without, in percentage points'),
        note: `Over ${pluralize(row.prompts, 'prompt')}: ${pluralize(row.no_search_answers, 'answer')} without search, ${pluralize(row.web_search_answers, 'answer')} with search`,
    }
}

/** One row per engine that answered without search in the window, in the usual engine order. */
export const memoryVsSearchRows = (overview: AEOPromptSetOverviewApi): MemoryVsSearchRow[] => {
    const order = sortEngines(overview.memory_vs_search.map((row) => row.engine))
    return [...overview.memory_vs_search]
        .sort((a, b) => order.indexOf(a.engine) - order.indexOf(b.engine))
        .map(memoryVsSearchRow)
}
