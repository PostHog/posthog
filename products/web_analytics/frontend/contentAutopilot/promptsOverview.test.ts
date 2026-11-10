import type { AEOPromptSetOverviewApi } from '../generated/api.schemas'
import { EXAMPLE_MEMORY_VS_SEARCH, EXAMPLE_PROMPT_SET_OVERVIEW } from './contentAutopilotStoryFixtures'
import { memoryVsSearchRows, promptsOverviewHasChecks, promptsOverviewKpis } from './promptsOverview'

const overview = (
    current: Partial<AEOPromptSetOverviewApi['current']>,
    previous: Partial<AEOPromptSetOverviewApi['previous']> = {}
): AEOPromptSetOverviewApi => ({
    ...EXAMPLE_PROMPT_SET_OVERVIEW,
    current: { ...EXAMPLE_PROMPT_SET_OVERVIEW.current, ...current },
    previous: { ...EXAMPLE_PROMPT_SET_OVERVIEW.previous, ...previous },
})

describe('promptsOverview', () => {
    it('words each KPI against the window before', () => {
        expect(promptsOverviewKpis(EXAMPLE_PROMPT_SET_OVERVIEW)).toEqual({
            promptsTracked: { value: '42', note: '44 ran in the last 30 days, 31 of them cited', delta: null },
            checks: {
                value: '2,520',
                note: '60 checks failed',
                delta: { label: '+120', direction: 'up', tooltip: 'Against the 30 days before' },
            },
            mentionRate: {
                value: '60%',
                note: '1,476 of 2,460 answers',
                delta: {
                    label: 'No change',
                    direction: 'flat',
                    tooltip: 'Against the 30 days before, in percentage points',
                },
            },
            citationRate: {
                value: '40%',
                note: '984 of 2,460 answers',
                delta: {
                    label: '+5 pts',
                    direction: 'up',
                    tooltip: 'Against the 30 days before, in percentage points',
                },
            },
            position: {
                value: '#2.3',
                note: 'Over 984\u00a0cited answers',
                delta: { label: '0.5 better', direction: 'up', tooltip: 'Against the 30 days before. Lower is better' },
            },
        })
    })

    it.each([
        ['a worse rank reads as a loss', 2.0, 1.5, { label: '0.5 worse', direction: 'down' }],
        ['the same rank', 2.0, 2.0, { label: 'No change', direction: 'flat' }],
        ['no rank before', 2.0, null, null],
    ])('compares the average position when %s', (_name, now, before, expected) => {
        const delta = promptsOverviewKpis(overview({ avg_position: now }, { avg_position: before })).position.delta
        expect(delta && { label: delta.label, direction: delta.direction }).toEqual(expected)
    })

    it('has no position without a cited answer', () => {
        expect(promptsOverviewKpis(overview({ cited: 0, avg_position: null })).position).toEqual({
            value: 'Not cited',
            note: 'No cited answers in the last 30 days',
            delta: null,
        })
    })

    it.each([
        [
            'no previous window',
            overview({}, { checks: 0, failed: 0, cited: 0, mentioned: 0, citation_rate: null, mention_rate: null }),
            { checks: null, citationRate: null },
        ],
        [
            'only failed checks in the current window',
            overview({ checks: 5, failed: 5, cited: 0, mentioned: 0, citation_rate: null, mention_rate: null }),
            {
                checks: { label: '-2395', direction: 'down', tooltip: 'Against the 30 days before' },
                citationRate: null,
            },
        ],
    ])('has no delta with %s', (_name, data, expected) => {
        const kpis = promptsOverviewKpis(data)
        expect(kpis.checks.delta).toEqual(expected.checks)
        expect(kpis.citationRate.delta).toEqual(expected.citationRate)
    })

    it.each([
        ['none of them', { prompts: 3, prompts_cited: 0 }, '3 ran in the last 30 days, none of them cited'],
        ['all of them', { prompts: 3, prompts_cited: 3 }, '3 ran in the last 30 days, all of them cited'],
        ['no run', { prompts: 0, prompts_cited: 0 }, 'None ran in the last 30 days'],
    ])('describes the cited prompts when %s', (_name, counts, note) => {
        expect(promptsOverviewKpis(overview(counts)).promptsTracked.note).toBe(note)
    })

    it('has checks only when a window has one', () => {
        expect(promptsOverviewHasChecks(EXAMPLE_PROMPT_SET_OVERVIEW)).toBe(true)
        expect(promptsOverviewHasChecks(overview({ checks: 0 }, { checks: 3 }))).toBe(true)
        expect(promptsOverviewHasChecks(overview({ checks: 0 }, { checks: 0 }))).toBe(false)
    })

    it.each([
        [
            'search answers for the same prompts',
            EXAMPLE_MEMORY_VS_SEARCH,
            [
                {
                    label: 'Claude',
                    summary: 'Without searching, Claude mentions you in 31% of answers; with search, 47%.',
                    gap: '+16 pts',
                    note: 'Over 42 prompts: 42 answers without search, 210 answers with search',
                },
                {
                    label: 'ChatGPT',
                    summary: 'Without searching, ChatGPT mentions you in 51% of answers; with search, 45%.',
                    gap: '-6 pts',
                    note: 'Over 42 prompts: 41 answers without search, 205 answers with search',
                },
            ],
        ],
        [
            'no search answers for the same prompts',
            [
                {
                    ...EXAMPLE_MEMORY_VS_SEARCH[1],
                    prompts: 1,
                    no_search_answers: 1,
                    no_search_mentioned: 1,
                    no_search_mention_rate: 1,
                    web_search_answers: 0,
                    web_search_mentioned: 0,
                    web_search_mention_rate: null,
                },
            ],
            [
                {
                    label: 'Claude',
                    summary:
                        'Without searching, Claude mentions you in 100% of answers. It has no answers with search for the same prompts yet.',
                    gap: null,
                    note: 'Over 1 prompt: 1 answer without search, 0 answers with search',
                },
            ],
        ],
        ['no no-search checks yet', [], []],
    ])('compares memory and search with %s', (_name, comparison, expected) => {
        const rows = memoryVsSearchRows({ ...EXAMPLE_PROMPT_SET_OVERVIEW, memory_vs_search: comparison })
        expect(
            rows.map((row) => ({
                label: row.label,
                summary: row.summary,
                gap: row.gap?.label ?? null,
                note: row.note.replace(/\u00a0/g, ' '),
            }))
        ).toEqual(expected)
    })
})
