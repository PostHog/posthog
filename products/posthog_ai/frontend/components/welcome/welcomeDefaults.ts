// Default, overridable content for the Welcome primitive. Shipped here so both consumers (the tasks
// composer and the new PostHog AI welcome) share one source; pass your own list to override.

import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

export const DEFAULT_HEADLINES: readonly string[] = [
    'How can I help you build?',
    'What are you curious about?',
    'How can I help you understand users?',
    'What do you want to know today?',
]

/**
 * Pick a headline from `headlines`. Forces the first one under Storybook so visual snapshots stay stable;
 * with a `seed` it's deterministic, otherwise it rotates at random. Call once and hold the result (e.g. in a
 * logic reducer) — calling it on every render would reshuffle the headline.
 */
export function pickHeadline(headlines: readonly string[] = DEFAULT_HEADLINES, seed?: number): string {
    if (headlines.length === 0) {
        return ''
    }
    if (inStorybook() || inStorybookTestRunner()) {
        return headlines[0]
    }
    const index = seed !== undefined ? seed % headlines.length : Math.floor(Math.random() * headlines.length)
    return headlines[index]
}
