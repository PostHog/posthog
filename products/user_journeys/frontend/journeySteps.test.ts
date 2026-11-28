import {
    JourneyDraft,
    MAX_STEPS,
    draftToStep,
    emptyDraft,
    emptyStep,
    moveStep,
    parseJourneyPrefill,
    serverErrorKey,
    validateDraft,
} from './journeySteps'

const PAGEVIEW = { type: 'pageview', url: 'https://example.com/pricing', url_matching: 'exact' }
const CLICK = { type: 'element_click', selector: 'button.signup', text: 'Sign up' }

function stepShapes(draft: JourneyDraft): Record<string, string>[] {
    return draft.steps.map(({ type, url, url_matching, selector, text, href }) => ({
        type,
        url,
        url_matching,
        selector,
        text,
        href,
    }))
}

function validDraft(): JourneyDraft {
    const draft = emptyDraft()
    draft.name = 'Sign up'
    draft.steps[0].url = '/pricing'
    draft.steps[1].selector = 'button.signup'
    return draft
}

describe('journeySteps', () => {
    describe('parseJourneyPrefill', () => {
        it('returns nothing when the link has no prefill params', () => {
            expect(parseJourneyPrefill({ unrelated: 'x' })).toBeNull()
        })

        test.each([
            ['a JSON string', JSON.stringify([PAGEVIEW, CLICK])],
            ['an array kea-router already parsed', [PAGEVIEW, CLICK]],
        ])('reads steps given as %s', (_, steps) => {
            const prefill = parseJourneyPrefill({ name: 'Sign up', steps, source: 'toolbar' })

            expect(prefill?.stepsSkipped).toBe(false)
            expect(prefill?.draft).toMatchObject({ name: 'Sign up', source: 'toolbar' })
            expect(stepShapes(prefill!.draft)).toEqual([
                {
                    type: 'pageview',
                    url: 'https://example.com/pricing',
                    url_matching: 'exact',
                    selector: '',
                    text: '',
                    href: '',
                },
                {
                    type: 'element_click',
                    url: '',
                    url_matching: 'exact',
                    selector: 'button.signup',
                    text: 'Sign up',
                    href: '',
                },
            ])
        })

        test.each([
            ['malformed JSON', '[{"type": "pageview"'],
            ['JSON that is not a list', '{"type": "pageview"}'],
            ['a number', 42],
        ])('keeps the default steps and flags the skip when steps are %s', (_, steps) => {
            const prefill = parseJourneyPrefill({ name: 'Sign up', steps })

            expect(prefill?.stepsSkipped).toBe(true)
            expect(prefill?.draft.steps.map((step) => step.type)).toEqual(['pageview', 'element_click'])
        })

        it('drops unreadable steps one by one and keeps the rest', () => {
            const prefill = parseJourneyPrefill({
                steps: [
                    PAGEVIEW,
                    null,
                    'pageview',
                    { type: 'script', url: '/x' },
                    { type: 'pageview', url: '' },
                    { type: 'pageview', url: '/a', url_matching: 'glob' },
                    { type: 'element_click', selector: '' },
                    { type: 'element_click', selector: '#ok', text: { html: '<b>' } },
                    CLICK,
                ],
            })

            expect(prefill?.stepsSkipped).toBe(true)
            expect(prefill?.draft.steps.map((step) => step.url || step.selector)).toEqual([
                'https://example.com/pricing',
                'button.signup',
            ])
        })

        it('keeps only the first steps up to the limit', () => {
            const steps = Array.from({ length: MAX_STEPS + 3 }, (_, index) => ({ type: 'pageview', url: `/${index}` }))

            const prefill = parseJourneyPrefill({ steps })

            expect(prefill?.stepsSkipped).toBe(true)
            expect(prefill?.draft.steps).toHaveLength(MAX_STEPS)
            expect(prefill?.draft.steps[MAX_STEPS - 1].url).toBe(`/${MAX_STEPS - 1}`)
        })

        test.each([
            ['a number kea-router parsed from the name', { name: 404 }, '404', 'manual'],
            ['an unknown source', { name: 'Checkout', source: 'admin' }, 'Checkout', 'manual'],
            ['a name that is not text', { name: ['x'], description: 'Why' }, '', 'manual'],
        ])('reads %s safely', (_, params, name, source) => {
            expect(parseJourneyPrefill(params)?.draft).toMatchObject({ name, source })
        })
    })

    describe('validateDraft', () => {
        test.each<[string, (draft: JourneyDraft) => void, Record<string, string>]>([
            ['a valid journey', () => {}, {}],
            ['a blank name', (draft) => (draft.name = '  '), { name: 'Give the journey a name.' }],
            ['one step', (draft) => draft.steps.pop(), { steps: 'Add at least 2 steps.' }],
            [
                'more steps than the limit',
                (draft) =>
                    draft.steps.push(...Array.from({ length: MAX_STEPS }, () => ({ ...emptyStep(), url: '/a' }))),
                { steps: `Use at most ${MAX_STEPS} steps.` },
            ],
            [
                'a blank selector',
                (draft) => (draft.steps[1].selector = ' '),
                { 'steps.1.selector': 'Enter a CSS selector for the element.' },
            ],
            ['a pageview with no URL', (draft) => (draft.steps[0].url = ''), { 'steps.0.url': 'Enter the page URL.' }],
            [
                'an invalid regex',
                (draft) => {
                    draft.steps[0].url = '(unclosed'
                    draft.steps[0].url_matching = 'regex'
                },
                { 'steps.0.url': 'Enter a valid regular expression.' },
            ],
            [
                'a conversion window past a day',
                (draft) => (draft.conversion_window_minutes = 24 * 60 + 1),
                { conversion_window_minutes: 'Enter a whole number of minutes from 1 to 1440.' },
            ],
            [
                'an empty conversion window',
                (draft) => (draft.conversion_window_minutes = undefined),
                { conversion_window_minutes: 'Enter a whole number of minutes from 1 to 1440.' },
            ],
            ['a full start URL', (draft) => (draft.start_url = 'https://example.com/pricing'), {}],
            [
                'a start URL without a scheme',
                (draft) => (draft.start_url = 'example.com/pricing'),
                { start_url: 'Enter a full URL, starting with http:// or https://.' },
            ],
            [
                'a start URL with credentials',
                (draft) => (draft.start_url = 'https://me:secret@example.com/'),
                { start_url: 'Remove the user name and password from the URL.' },
            ],
        ])('reports %s', (_, change, expected) => {
            const draft = validDraft()
            change(draft)
            expect(validateDraft(draft)).toEqual(expected)
        })
    })

    describe('moveStep', () => {
        const steps = [emptyStep(), emptyStep(), emptyStep()]
        const keys = steps.map((step) => step.key)

        test.each<[string, string, -1 | 1, string[]]>([
            ['up', keys[1], -1, [keys[1], keys[0], keys[2]]],
            ['down', keys[1], 1, [keys[0], keys[2], keys[1]]],
            ['the first step up', keys[0], -1, keys],
            ['the last step down', keys[2], 1, keys],
            ['an unknown step', 'missing', 1, keys],
        ])('moves %s', (_, key, direction, expected) => {
            expect(moveStep(steps, key, direction).map((step) => step.key)).toEqual(expected)
        })
    })

    it('sends blank optional click fields as null, which the API reads as "match any"', () => {
        const step = { ...emptyStep('element_click'), selector: ' #buy ', text: '  ', href: '', url: '' }

        expect(draftToStep(step)).toEqual({
            type: 'element_click',
            selector: '#buy',
            text: null,
            href: null,
            url: null,
            url_matching: 'exact',
        })
    })

    test.each([
        ['steps__1__selector', 'steps.1.selector'],
        ['steps', 'steps'],
        ['steps__0', 'steps'],
        ['name', 'name'],
        ['conversion_window_minutes', 'conversion_window_minutes'],
        ['non_field_errors', null],
        [null, null],
    ])('maps the API error attr %s to the form field %s', (attr, expected) => {
        expect(serverErrorKey(attr)).toEqual(expected)
    })
})
