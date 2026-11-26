import { AI_LAB_SHADES, type AiLab, MAIN_LAB_SHADE } from 'lib/components/BrandMark/aiLabShades'
import type { BrandMarkName } from 'lib/components/BrandMark/brandMarks'
import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'

import type {
    AEOPromptCheckApi,
    AEOPromptApi,
    AEOPromptImportResultApi,
    BrandedSegmentEnumApi,
    PatchedAEOPromptUpdateRequestApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

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

/** Topics that differ only in letter case are one topic, as the API counts them. */
export const sameTopic = (a: string | null | undefined, b: string | null | undefined): boolean =>
    a !== null && a !== undefined && b !== null && b !== undefined && a.toLowerCase() === b.toLowerCase()

export const unavailableEngineReason = (setting: { available: boolean }): string | undefined =>
    setting.available ? undefined : "This engine isn't set up for this project yet."

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

const SEGMENT_PROMPTS: Record<BrandedSegmentEnumApi, string> = {
    all: 'all prompts',
    branded: 'prompts that name your brand',
    non_branded: "prompts that don't name your brand",
}

export const segmentPrompts = (segment: BrandedSegmentEnumApi): string => SEGMENT_PROMPTS[segment]

/** How many answers the numbers on a tab come from, and which prompts they answered. */
export const brandedAnswersNote = (segment: BrandedSegmentEnumApi, answers: number): string =>
    `From ${pluralize(answers, 'answer')} to ${SEGMENT_PROMPTS[segment]}.`

interface ReportWindow {
    /** First and last day of a report's window, as the API returns them: "2026-11-01". */
    window_from: string
    window_to: string
}

const windowDay = (day: string): string => dayjs(day).format('MMM D')

/** A report's window as it reads in a sentence, such as "from Oct 18 to Nov 17" or "on Nov 17". */
export const windowRange = ({ window_from, window_to }: ReportWindow): string =>
    window_from === window_to
        ? `on ${windowDay(window_to)}`
        : `from ${windowDay(window_from)} to ${windowDay(window_to)}`

/** The heading over a tab's numbers, such as "Oct 18 to Nov 17, Claude, topic Pricing". */
export const filtersHeading = ({
    window_from,
    window_to,
    engine,
    topic,
}: ReportWindow & {
    engine?: string | null
    topic?: string | null
}): string =>
    [
        window_from === window_to ? windowDay(window_to) : `${windowDay(window_from)} to ${windowDay(window_to)}`,
        engine ? engineLabel(engine) : 'all engines',
        ...(topic === null || topic === undefined ? [] : [topic ? `topic ${topic}` : 'prompts with no topic']),
    ].join(', ')
