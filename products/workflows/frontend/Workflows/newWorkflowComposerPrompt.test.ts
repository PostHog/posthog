import { combineUrl } from 'kea-router'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'

import {
    MAX_COMPOSER_PROMPT_LENGTH,
    readComposerPrompt,
    urlForNewWorkflowComposerWithPrompt,
} from './newWorkflowComposerPrompt'

describe('newWorkflowComposerPrompt', () => {
    it('builds a composer URL that carries the trimmed prompt and the source', () => {
        const { pathname, searchParams } = combineUrl(
            urlForNewWorkflowComposerWithPrompt('  Send a welcome email  ', 'cdp_destination_cross_sell')
        )

        expect(removeProjectIdIfPresent(pathname)).toBe('/workflows/new/workflow')
        expect(searchParams).toEqual({
            mode: 'ai',
            prompt: 'Send a welcome email',
            source: 'cdp_destination_cross_sell',
        })
    })

    // The prompt is URL-controlled, so what the composer receives is bounded and always text.
    it.each([
        { name: 'no param', searchParams: {}, expected: null },
        { name: 'blank text', searchParams: { prompt: '   ' }, expected: null },
        { name: 'an object', searchParams: { prompt: { a: 1 } }, expected: null },
        { name: 'a number the router parsed', searchParams: { prompt: 42 }, expected: '42' },
        { name: 'text with padding', searchParams: { prompt: '  Win back users  ' }, expected: 'Win back users' },
        {
            name: 'an overlong prompt',
            searchParams: { prompt: 'x'.repeat(MAX_COMPOSER_PROMPT_LENGTH + 500) },
            expected: 'x'.repeat(MAX_COMPOSER_PROMPT_LENGTH),
        },
    ])('readComposerPrompt returns $expected for $name', ({ searchParams, expected }) => {
        expect(readComposerPrompt(searchParams)).toBe(expected)
    })
})
