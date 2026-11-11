import type { AEOPromptEngineCheckApi, ContentAutopilotOpportunityApi } from '../generated/api.schemas'
import { EXAMPLE_OPPORTUNITIES, EXAMPLE_PROMPTS } from './contentAutopilotStoryFixtures'
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
        const check = (engine: string, search_queries: string[]): AEOPromptEngineCheckApi => ({
            ...EXAMPLE_PROMPTS[0].latest_checks[0],
            engine,
            search_queries,
        })

        it.each<[string, AEOPromptEngineCheckApi[], { primary: string | null; distinct: number }]>([
            ['no searches', [], { primary: null, distinct: 0 }],
            [
                'the search most engines ran wins, case ignored',
                [
                    check('openai-web-search', ['Best session replay', 'replay pricing']),
                    check('claude-web-search', ['best session replay']),
                ],
                { primary: 'best session replay', distinct: 2 },
            ],
            [
                'blank and repeated searches are skipped',
                [check('claude-web-search', ['  ', 'Same', 'same '])],
                { primary: 'Same', distinct: 1 },
            ],
            [
                'one engine, first search',
                [check('claude-web-search', ['first', 'second'])],
                { primary: 'first', distinct: 2 },
            ],
        ])('picks the search to show with %s', (_name, latest_checks, expected) => {
            const result = promptSearches({ latest_checks })
            expect({ primary: result.primary, distinct: result.distinct }).toEqual(expected)
        })
    })
})
