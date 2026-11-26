import type { AEOPromptSetOverviewApi } from '../generated/api.schemas'
import { EXAMPLE_PROMPT_SET_OVERVIEW } from './contentAutopilotStoryFixtures'
import { engineTopicGrid, overviewTiles, promptsOverviewHasChecks } from './promptsOverview'

const overview = (
    current: Partial<AEOPromptSetOverviewApi['current']>,
    previous: Partial<AEOPromptSetOverviewApi['previous']> = {}
): AEOPromptSetOverviewApi => ({
    ...EXAMPLE_PROMPT_SET_OVERVIEW,
    current: { ...EXAMPLE_PROMPT_SET_OVERVIEW.current, ...current },
    previous: { ...EXAMPLE_PROMPT_SET_OVERVIEW.previous, ...previous },
})

describe('promptsOverview', () => {
    it.each([
        ['shares of the answered checks', {}, { prompts: '42', visibility: '60%', cited: '40%', position: '#2.3' }],
        [
            'no answered checks',
            { checks: 5, failed: 5, avg_position: null },
            { prompts: '42', visibility: '-', cited: '-', position: 'Not cited' },
        ],
    ])('gives each headline tile only its value, from %s', (_name, current, tiles) => {
        expect(overviewTiles(overview(current))).toEqual(tiles)
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
