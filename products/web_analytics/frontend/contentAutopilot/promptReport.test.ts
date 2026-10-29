import type { AEOPromptStatsApi } from '../generated/api.schemas'
import { EXAMPLE_PROMPT_STATS } from './contentAutopilotStoryFixtures'
import { promptConsensusMatrix, promptReportKpis, promptSentimentSummary } from './promptReport'

const day = (
    date: string,
    engine: string,
    counts: Partial<Pick<AEOPromptStatsApi['daily'][number], 'checks' | 'cited' | 'mentioned' | 'failed'>>
): AEOPromptStatsApi['daily'][number] => ({ date, engine, checks: 1, cited: 0, mentioned: 0, failed: 0, ...counts })

const stats = (daily: AEOPromptStatsApi['daily'], overrides: Partial<AEOPromptStatsApi> = {}): AEOPromptStatsApi => ({
    ...EXAMPLE_PROMPT_STATS,
    daily_from: '2026-09-01',
    daily_to: '2026-09-10',
    daily,
    ...overrides,
})

describe('promptReport', () => {
    describe('promptReportKpis', () => {
        it('pools the window and compares the latest answered day against it', () => {
            const kpis = promptReportKpis(
                stats([
                    day('2026-09-01', 'a', { cited: 1, mentioned: 1 }),
                    day('2026-09-01', 'b', { mentioned: 1 }),
                    day('2026-09-02', 'a', { failed: 1 }),
                    day('2026-09-05', 'a', {}),
                    day('2026-09-05', 'b', { cited: 1, mentioned: 1 }),
                    // The latest day only failed, so the day before it is the latest with an answer.
                    day('2026-09-10', 'a', { failed: 1 }),
                ])
            )

            expect(kpis).toEqual({
                answers: 4,
                days: 10,
                visibility: { average: 0.75, latest: 0.5, latestDate: '2026-09-05', delta: -0.25 },
                citation: { average: 0.5, latest: 0.5, latestDate: '2026-09-05', delta: 0 },
            })
        })

        it.each([
            ['no checks', []],
            ['only failed checks', [day('2026-09-03', 'a', { failed: 1 })]],
        ])('has no rates with %s', (_name, daily) => {
            const kpis = promptReportKpis(stats(daily))
            expect(kpis.answers).toBe(0)
            expect(kpis.visibility).toEqual({ average: null, latest: null, latestDate: null, delta: null })
            expect(kpis.citation).toEqual(kpis.visibility)
        })
    })

    it('builds the consensus matrix in engine order and drops engines without answers', () => {
        const matrix = promptConsensusMatrix(
            stats([], {
                consensus: [
                    { engine: 'b', domain: 'x.example', checks_citing: 1, checks: 4 },
                    { engine: 'b', domain: 'y.example', checks_citing: 4, checks: 4 },
                    { engine: 'a', domain: 'x.example', checks_citing: 2, checks: 2 },
                    { engine: 'a', domain: 'y.example', checks_citing: 0, checks: 2 },
                    { engine: 'c', domain: 'x.example', checks_citing: 0, checks: 0 },
                ],
            }),
            ['a', 'b', 'c']
        )

        expect(matrix.domains).toEqual(['x.example', 'y.example'])
        expect(matrix.rows).toEqual([
            {
                engine: 'a',
                checks: 2,
                cells: [
                    { domain: 'x.example', checksCiting: 2, share: 1 },
                    { domain: 'y.example', checksCiting: 0, share: 0 },
                ],
            },
            {
                engine: 'b',
                checks: 4,
                cells: [
                    { domain: 'x.example', checksCiting: 1, share: 0.25 },
                    { domain: 'y.example', checksCiting: 4, share: 1 },
                ],
            },
        ])
    })

    it.each([
        [
            'some scored',
            [
                { engine: 'a', positive: 3, neutral: 1, negative: 0, unscored: 2 },
                { engine: 'b', positive: 0, neutral: 0, negative: 0, unscored: 5 },
            ],
            {
                positive: 3,
                neutral: 1,
                negative: 0,
                unscored: 7,
                scored: 4,
                byEngine: [{ engine: 'a', scored: 4, positive: 3, neutral: 1, negative: 0 }],
            },
        ],
        // Scoring off: mentions exist but nothing is scored, so the UI must not claim there are no mentions.
        [
            'mentions but nothing scored',
            [{ engine: 'a', positive: 0, neutral: 0, negative: 0, unscored: 4 }],
            { positive: 0, neutral: 0, negative: 0, unscored: 4, scored: 0, byEngine: [] },
        ],
    ])(
        'sums sentiment across engines with %s and lists only engines with scored answers',
        (_name, sentiment, expected) => {
            expect(promptSentimentSummary(stats([], { sentiment }), ['b', 'a'])).toEqual(expected)
        }
    )
})
