import { AI_LAB_SHADES, type AiLab, MAIN_LAB_SHADE } from 'lib/components/BrandMark/aiLabShades'
import type { BrandMarkName } from 'lib/components/BrandMark/brandMarks'
import { pluralize } from 'lib/utils/strings'
import { parseWebAnalyticsURL } from 'scenes/web-analytics/common'

import type {
    AEOPromptCheckApi,
    AEOPromptApi,
    AEOPromptImportResultApi,
    BrandedSegmentEnumApi,
    ContentAutopilotOpportunityApi,
    ContentAutopilotProposalListApi,
    PatchedAEOPromptUpdateRequestApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

const OPPORTUNITIES_STALE_AFTER_MS = 60 * 60 * 1000

export const ENGINE_LABELS: Record<string, string> = {
    'claude-web-search': 'Claude',
    'openai-web-search': 'ChatGPT',
    'exa-answer': 'Exa',
    'gemini-google-search': 'Gemini',
    'perplexity-web-search': 'Perplexity',
    'claude-no-search': 'Claude (no search)',
    'openai-no-search': 'ChatGPT (no search)',
}

export const engineLabel = (engine: string): string => ENGINE_LABELS[engine] ?? engine

/** Engines that answer from training data alone. They never cite, so their columns show mentions. */
const NO_SEARCH_ENGINES = new Set(['claude-no-search', 'openai-no-search'])

export const isNoSearchEngine = (engine: string): boolean => NO_SEARCH_ENGINES.has(engine)

// Matched on the id's prefix, so a new engine from the same assistant (a no-search variant, say) gets
// its mark and color without an entry here.
const ENGINE_BRANDS: { prefix: string; mark: BrandMarkName; lab?: AiLab }[] = [
    { prefix: 'claude', mark: 'Claude', lab: 'Anthropic' },
    { prefix: 'openai', mark: 'OpenAI', lab: 'OpenAI' },
    { prefix: 'gemini', mark: 'Gemini', lab: 'Google' },
    { prefix: 'perplexity', mark: 'Perplexity' },
]

const engineBrand = (engine: string): (typeof ENGINE_BRANDS)[number] | undefined =>
    ENGINE_BRANDS.find(({ prefix }) => engine.startsWith(prefix))

export const engineMark = (engine: string): BrandMarkName => engineBrand(engine)?.mark ?? 'Unbranded model'

/** The engine's lab color, a shade darker for engines that answer without searching the web. Undefined for
 *  engines without a lab, so charts fall back to the theme palette. */
export const engineColor = (engine: string): string | undefined => {
    const lab = engineBrand(engine)?.lab
    if (!lab) {
        return undefined
    }
    return AI_LAB_SHADES[lab][isNoSearchEngine(engine) ? MAIN_LAB_SHADE - 1 : MAIN_LAB_SHADE]
}

export interface PromptSearches {
    /** The search to show for the prompt: the one most engines ran, else the first one. */
    primary: string | null
    byEngine: { engine: string; queries: string[] }[]
    distinct: number
}

/** Matches the backend's search grouping: case and runs of whitespace are ignored. */
const searchKey = (query: string): string => query.trim().toLowerCase().split(/\s+/).join(' ')

/** The web searches each engine ran on its latest check of a prompt. */
export const promptSearches = (prompt: Pick<AEOPromptApi, 'latest_checks'>): PromptSearches => {
    const byEngine = sortEngines(prompt.latest_checks.map((check) => check.engine))
        .map((engine) => {
            const queries = prompt.latest_checks.find((check) => check.engine === engine)?.search_queries ?? []
            const unique = new Map<string, string>()
            for (const query of queries) {
                const key = searchKey(query)
                if (key && !unique.has(key)) {
                    unique.set(key, query.trim())
                }
            }
            return { engine, queries: [...unique.values()] }
        })
        .filter(({ queries }) => queries.length > 0)
    const engineCounts = new Map<string, { query: string; engines: number }>()
    for (const { queries } of byEngine) {
        for (const query of queries) {
            const key = searchKey(query)
            const entry = engineCounts.get(key)
            engineCounts.set(key, { query: entry?.query ?? query, engines: (entry?.engines ?? 0) + 1 })
        }
    }
    let primary: { query: string; engines: number } | null = null
    for (const entry of engineCounts.values()) {
        if (!primary || entry.engines > primary.engines) {
            primary = entry
        }
    }
    return { primary: primary?.query ?? null, byEngine, distinct: engineCounts.size }
}

/** Known engines first, in a fixed order, so table columns don't move between pages. */
export const sortEngines = (engines: Iterable<string>): string[] => {
    const known = Object.keys(ENGINE_LABELS)
    const rank = (engine: string): number => (known.includes(engine) ? known.indexOf(engine) : known.length)
    return [...new Set(engines)].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
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

export const promptLines = (text: string): string[] => {
    const seen = new Set<string>()
    return text
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => {
            const key = line.toLowerCase()
            if (!line || seen.has(key)) {
                return false
            }
            seen.add(key)
            return true
        })
}

export const promptImportMessage = ({ created, updated, skipped }: AEOPromptImportResultApi): string => {
    const sentences = [
        created ? `Added ${pluralize(created, 'prompt')}. The next daily run checks new prompts.` : null,
        updated ? `Updated ${pluralize(updated, 'existing prompt')}.` : null,
        skipped ? `Skipped ${pluralize(skipped, 'prompt')} (empty, too long, or archived).` : null,
    ].filter(Boolean)
    return sentences.join(' ') || 'No prompts changed.'
}

export const promptEditPatch = (
    prompt: Pick<AEOPromptApi, 'prompt' | 'topic'>,
    text: string,
    topic: string
): PatchedAEOPromptUpdateRequestApi | null => {
    const patch: PatchedAEOPromptUpdateRequestApi = {}
    if (text.trim() !== prompt.prompt) {
        patch.prompt = text.trim()
    }
    if (topic.trim() !== prompt.topic) {
        patch.topic = topic.trim()
    }
    return Object.keys(patch).length ? patch : null
}

const normalizedPrompt = (text: string): string => text.trim().replace(/\s+/g, ' ').toLowerCase()

// An opportunity drafts from the text it was found for, so after an edit it stays hidden until a refresh matches it.
export const draftableOpportunity = (
    opportunityByPromptId: Record<string, ContentAutopilotOpportunityApi>,
    prompt: Pick<AEOPromptApi, 'id' | 'prompt'>
): ContentAutopilotOpportunityApi | null => {
    const opportunity = opportunityByPromptId[prompt.id]
    return opportunity && normalizedPrompt(opportunity.title) === normalizedPrompt(prompt.prompt) ? opportunity : null
}

const SEGMENT_PROMPTS: Record<BrandedSegmentEnumApi, string> = {
    all: 'all prompts',
    branded: 'prompts that name your brand',
    non_branded: "prompts that don't name your brand",
}

export const segmentPrompts = (segment: BrandedSegmentEnumApi): string => SEGMENT_PROMPTS[segment]

/** How many answers the numbers on a tab come from, and which prompts they answered. */
export const brandedAnswersNote = (segment: BrandedSegmentEnumApi, answers: number): string =>
    `From ${pluralize(answers, 'answer')} to ${SEGMENT_PROMPTS[segment]}.`
