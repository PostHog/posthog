import type { AEOPromptSetOverviewApi } from '../generated/api.schemas'
import { EXAMPLE_PROMPT_SET_OVERVIEW } from './contentAutopilotStoryFixtures'
import { promptsOverviewHasChecks, promptsOverviewKpis } from './promptsOverview'

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
})
