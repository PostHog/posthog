import { dayjs } from 'lib/dayjs'
import { parseWebAnalyticsURL } from 'scenes/web-analytics/common'

import type {
    AEOPromptCheckApi,
    AEOPromptStatsApi,
    ContentAutopilotOpportunityApi,
    ContentAutopilotProposalListApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

const OPPORTUNITIES_STALE_AFTER_MS = 60 * 60 * 1000

const ENGINE_LABELS: Record<string, string> = {
    'claude-web-search': 'Claude',
    'openai-web-search': 'ChatGPT',
    'exa-answer': 'Exa',
    'gemini-google-search': 'Gemini',
}

export const engineLabel = (engine: string): string => ENGINE_LABELS[engine] ?? engine

/** Known engines first, in a fixed order, so table columns don't move between pages. */
export const sortEngines = (engines: Iterable<string>): string[] => {
    const known = Object.keys(ENGINE_LABELS)
    const rank = (engine: string): number => (known.includes(engine) ? known.indexOf(engine) : known.length)
    return [...new Set(engines)].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
}

export type PromptHistoryCellStatus = 'cited' | 'not_cited' | 'failed' | 'no_run'

export interface PromptHistoryCell {
    date: string
    status: PromptHistoryCellStatus
    checks: number
    cited: number
    failed: number
}

export interface PromptHistoryGrid {
    dates: string[]
    rows: { engine: string; cells: PromptHistoryCell[] }[]
}

const historyCellStatus = ({
    checks,
    cited,
    failed,
}: Omit<PromptHistoryCell, 'date' | 'status'>): PromptHistoryCellStatus =>
    checks === 0 ? 'no_run' : cited > 0 ? 'cited' : failed === checks ? 'failed' : 'not_cited'

/** One cell per day and engine across the stats window, with days the engine did not run filled in. */
export const promptHistoryGrid = (stats: AEOPromptStatsApi, engines: string[]): PromptHistoryGrid => {
    const dates: string[] = []
    for (let day = dayjs(stats.daily_from); !day.isAfter(dayjs(stats.daily_to), 'day'); day = day.add(1, 'day')) {
        dates.push(day.format('YYYY-MM-DD'))
    }
    const byKey = new Map(stats.daily.map((row) => [`${row.engine}|${row.date}`, row]))
    return {
        dates,
        rows: engines.map((engine) => ({
            engine,
            cells: dates.map((date) => {
                const row = byKey.get(`${engine}|${date}`)
                const counts = { checks: row?.checks ?? 0, cited: row?.cited ?? 0, failed: row?.failed ?? 0 }
                return { date, status: historyCellStatus(counts), ...counts }
            }),
        })),
    }
}

export type ContentAutopilotPageTarget =
    | { isNewPage: true; path: string }
    | { isNewPage: false; path: string; url: string }

export const proposalPagePath = (proposal: Pick<ContentAutopilotProposalListApi, 'file_path' | 'target_url'>): string =>
    (proposal.target_url && parseWebAnalyticsURL(proposal.target_url).pathname) ||
    (proposal.file_path ? `/${proposal.file_path.replace(/\.mdx?$/, '')}` : '')

export const pageToUpdate = (
    opportunity: Pick<ContentAutopilotOpportunityApi, 'recommended_type' | 'target_url'>,
    proposal: ContentAutopilotProposalListApi | undefined
): ContentAutopilotPageTarget | null => {
    if (proposal && proposal.lifecycle_status !== 'generating') {
        const path = proposalPagePath(proposal)
        if (proposal.proposal_type === 'new_content' && path) {
            return { isNewPage: true, path }
        }
        if (proposal.proposal_type !== 'new_content' && proposal.target_url) {
            return { isNewPage: false, path, url: proposal.target_url }
        }
    }
    if (opportunity.recommended_type === 'page_improvement' && opportunity.target_url) {
        return {
            isNewPage: false,
            path: parseWebAnalyticsURL(opportunity.target_url).pathname ?? opportunity.target_url,
            url: opportunity.target_url,
        }
    }
    return null
}

export const opportunitiesNeedRefresh = (
    opportunities: Pick<ContentAutopilotOpportunityApi, 'last_refreshed_at'>[],
    now: number
): boolean => {
    const refreshedAt = opportunities
        .map(({ last_refreshed_at }) => Date.parse(last_refreshed_at))
        .filter((time) => !Number.isNaN(time))
    return refreshedAt.length === 0 || now - Math.max(...refreshedAt) > OPPORTUNITIES_STALE_AFTER_MS
}

// Checks recorded before prompts had versions carry no version. A prompt's text could not change
// before then, so those checks all ran the text that became version 1.
export const checkPromptVersion = (check: Pick<AEOPromptCheckApi, 'prompt_version'>): number =>
    check.prompt_version ?? 1
