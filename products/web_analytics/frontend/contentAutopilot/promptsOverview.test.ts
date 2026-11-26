import type { AEOPromptSetOverviewApi } from '../generated/api.schemas'
import { EXAMPLE_PROMPT_SET_OVERVIEW } from './contentAutopilotStoryFixtures'
import { engineTopicGrid, overviewMetricItems, promptsOverviewHasChecks } from './promptsOverview'

const overview = (
    current: Partial<AEOPromptSetOverviewApi['current']>,
    previous: Partial<AEOPromptSetOverviewApi['previous']> = {}
): AEOPromptSetOverviewApi => ({
    ...EXAMPLE_PROMPT_SET_OVERVIEW,
    current: { ...EXAMPLE_PROMPT_SET_OVERVIEW.current, ...current },
    previous: { ...EXAMPLE_PROMPT_SET_OVERVIEW.previous, ...previous },
})

describe('promptsOverview', () => {
    it('gives the headline numbers in Web analytics tile shape, each against the window before', () => {
        const [prompts, visibility, cited, position] = overviewMetricItems(EXAMPLE_PROMPT_SET_OVERVIEW)
        expect(prompts).toMatchObject({ key: 'prompts', kind: 'unit', value: 42 })
        expect(visibility).toMatchObject({ key: 'visibility', kind: 'percentage', value: 60 })
        expect(visibility.previous).toBeCloseTo(60)
        expect(cited).toMatchObject({ key: 'cited', kind: 'percentage', value: 40 })
        const before = cited.previous as number
        expect(cited.changeFromPreviousPct).toBeCloseTo(((40 - before) / before) * 100)
        expect(position).toMatchObject({ key: 'position', value: '#2.3', isIncreaseBad: true })
    })

    it('has no earlier value or change when the window before had no answers', () => {
        const [, visibility, , position] = overviewMetricItems(
            overview({}, { checks: 0, failed: 0, cited: 0, mentioned: 0, avg_position: null })
        )
        expect(visibility).toMatchObject({ previous: undefined, changeFromPreviousPct: undefined })
        expect(position).toMatchObject({ previous: undefined, changeFromPreviousPct: undefined })
    })

    it.each([
        ['none of them', { prompts: 3, prompts_cited: 0 }, '3 ran in this date range, none of them cited'],
        ['all of them', { prompts: 3, prompts_cited: 3 }, '3 ran in this date range, all of them cited'],
        ['no run', { prompts: 0, prompts_cited: 0 }, 'None ran in this date range'],
    ])('describes the cited prompts when %s', (_name, counts, note) => {
        expect(overviewMetricItems(overview(counts))[0].caption).toBe(note)
    })

    it('has checks only when a window has one', () => {
        expect(promptsOverviewHasChecks(EXAMPLE_PROMPT_SET_OVERVIEW)).toBe(true)
        expect(promptsOverviewHasChecks(overview({ checks: 0 }, { checks: 3 }))).toBe(true)
        expect(promptsOverviewHasChecks(overview({ checks: 0 }, { checks: 0 }))).toBe(false)
    })

    it('lays out a cell per topic and engine, and keeps a pair without an answer apart from a rate of zero', () => {
        const topic = (name: string): AEOPromptSetOverviewApi['topics'][number] => ({
            ...EXAMPLE_PROMPT_SET_OVERVIEW.topics[0],
            topic: name,
        })
        const pair = (
            engine: string,
            name: string,
            answers: number,
            mentioned: number
        ): AEOPromptSetOverviewApi['engine_topics'][number] => ({
            engine,
            topic: name,
            answers,
            mentioned,
            mention_rate: mentioned / answers,
        })

        const grid = engineTopicGrid({
            topics: [topic(''), topic('Flags'), topic('Replay'), topic('Surveys')],
            engine_topics: [
                pair('exa-answer', 'Flags', 4, 4),
                pair('exa-answer', 'Replay', 10, 0),
                pair('claude-web-search', '', 5, 1),
                pair('claude-web-search', 'Flags', 8, 5),
            ],
        })

        expect(grid.engines).toEqual(['claude-web-search', 'exa-answer'])
        expect(
            grid.rows.map((row) => [row.topic, ...row.cells.map((cell) => [cell.rate, cell.answers, cell.heat])])
        ).toEqual([
            ['Flags', [0.625, 8, 3], [1, 4, 4]],
            ['Replay', [null, 0, null], [0, 10, 0]],
            ['Surveys', [null, 0, null], [null, 0, null]],
            ['', [0.2, 5, 1], [null, 0, null]],
        ])
    })
})
