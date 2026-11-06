import type { AEOPromptEngineCheckApi, ContentAutopilotOpportunityApi } from '../generated/api.schemas'
import { EXAMPLE_OPPORTUNITIES } from './contentAutopilotStoryFixtures'
import { draftableOpportunity, promptSearches } from './utils'

describe('utils', () => {
    describe('draftableOpportunity', () => {
        const opportunity: ContentAutopilotOpportunityApi = {
            ...EXAMPLE_OPPORTUNITIES[0],
            aeo_prompt_id: 'prompt-1',
            title: 'Best session replay tool?',
        }
        const byPrompt = { 'prompt-1': opportunity }

        it.each([
            ['the same text', 'Best session replay tool?', true],
            ['the same text with other case and spacing', '  best   session replay TOOL? ', true],
            ['edited text', 'Best open source session replay tool?', false],
        ])('offers the opportunity for %s', (_name, text, expected) => {
            expect(draftableOpportunity(byPrompt, { id: 'prompt-1', prompt: text })).toBe(expected ? opportunity : null)
        })

        it('offers nothing for a prompt without an opportunity', () => {
            expect(draftableOpportunity(byPrompt, { id: 'prompt-2', prompt: 'Best session replay tool?' })).toBeNull()
        })
    })

    describe('promptSearches', () => {
        it.each<[string, AEOPromptEngineCheckApi[], { primary: string | null; distinct: number }]>([
            ['no searches', [], { primary: null, distinct: 0 }],
            [
                'the search most engines ran wins, case ignored',
                [
                    {
                        engine: 'openai-web-search',
                        cited: false,
                        check_failed: false,
                        search_queries: ['Best session replay', 'replay pricing'],
                        checked_at: '2026-11-01T00:00:00Z',
                    },
                    {
                        engine: 'claude-web-search',
                        cited: false,
                        check_failed: false,
                        search_queries: ['best session replay'],
                        checked_at: '2026-11-01T00:00:00Z',
                    },
                ],
                { primary: 'best session replay', distinct: 2 },
            ],
            [
                'one engine, first search',
                [
                    {
                        engine: 'claude-web-search',
                        cited: false,
                        check_failed: false,
                        search_queries: ['first', 'second'],
                        checked_at: '2026-11-01T00:00:00Z',
                    },
                ],
                { primary: 'first', distinct: 2 },
            ],
        ])('picks the search to show with %s', (_name, latest_checks, expected) => {
            const result = promptSearches({ latest_checks })
            expect({ primary: result.primary, distinct: result.distinct }).toEqual(expected)
        })
    })
})
