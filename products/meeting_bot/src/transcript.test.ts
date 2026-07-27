import { describe, expect, it } from 'vitest'

import { findTrigger, TranscriptBuffer } from './transcript'

describe('transcript', () => {
    it.each([
        ['Hey PostHog, what is the DAU for the pricing page?', 'what is the DAU for the pricing page?'],
        ['hey post hog check the DAU for the blah page', 'check the DAU for the blah page'],
        ['Okay post hoc, how many signups yesterday?', 'how many signups yesterday?'],
        ['Hi Posthawk - what about last week', 'what about last week'],
        ['So anyway, hey PostHog: break that down by country', 'break that down by country'],
    ])('fires on %j and returns the question after the trigger', (heard, prompt) => {
        expect(findTrigger(heard, 'hey posthog')).toEqual({ prompt })
    })

    it.each([
        // Saying the product name is constant in a PostHog meeting, so the wake word has to carry the trigger.
        'we should ship this in PostHog next week',
        'PostHog already tracks that',
        // The wake word is present but attached to someone else, not the bot.
        'hey team, PostHog is great for this',
        'hey, can you share your screen?',
    ])('stays quiet on %j', (heard) => {
        expect(findTrigger(heard, 'hey posthog')).toBeNull()
    })

    it('returns an empty question when the speaker has only said the trigger so far', () => {
        expect(findTrigger('Hey PostHog...', 'hey posthog')).toEqual({ prompt: '' })
    })

    it('drops utterances that fall outside the window', () => {
        const buffer = new TranscriptBuffer(60)
        const start = 1_000_000

        buffer.add({ speaker: 'Ana', text: 'old news', at: start })
        buffer.add({ speaker: 'Ben', text: 'still relevant', at: start + 55_000 })

        expect(buffer.context(start + 70_000)).toBe('Ben: still relevant')
    })
})
