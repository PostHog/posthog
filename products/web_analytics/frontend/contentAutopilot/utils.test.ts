import type { ContentAutopilotOpportunityApi } from '../generated/api.schemas'
import { EXAMPLE_OPPORTUNITIES } from './contentAutopilotStoryFixtures'
import { draftableOpportunity } from './utils'

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
