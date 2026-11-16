import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type {
    AEOPromptSetCountsApi,
    AEOPromptSetOverviewApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import { type KpiCardContent, countDelta, pointsDelta } from './promptReport'

export interface PromptsOverviewKpis {
    promptsTracked: KpiCardContent
    checks: KpiCardContent
    mentionRate: KpiCardContent
    citationRate: KpiCardContent
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

/** The four numbers at the top of the prompts tab, each against the window before. */
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
    }
}

/** Without a single check in either window, the overview has nothing to show. */
export const promptsOverviewHasChecks = (overview: AEOPromptSetOverviewApi): boolean =>
    overview.current.checks > 0 || overview.previous.checks > 0
