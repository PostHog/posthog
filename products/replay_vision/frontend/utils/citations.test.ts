import { type Segment, citedTextToPlainText, parseCitedSegments } from './citations'

describe('parseCitedSegments', () => {
    const text = (value: string): Segment => ({ kind: 'text', value })
    const chip = (seconds: number): Segment => ({ kind: 'chip', timestamp_ms: seconds * 1000 })

    it.each<{ name: string; text: string; segments: unknown; expected: Segment[] }>([
        {
            name: 'splits a leaked comma-joined marker inside a persisted text segment into one chip per second',
            text: 'ignored when segments exist',
            segments: [text('changed the filter (t 1437, 1441), scrolling'), chip(1479)],
            expected: [text('changed the filter'), chip(1437), chip(1441), text(', scrolling'), chip(1479)],
        },
        {
            name: 'handles the comma-joined variant that repeats the t prefix',
            text: '',
            segments: [text('Clicked twice (t 39, t 57) before it responded')],
            expected: [text('Clicked twice'), chip(39), chip(57), text(' before it responded')],
        },
        {
            name: 'parses markers straight from the text when no segments were persisted',
            text: 'The user retried (t 12) twice.',
            segments: undefined,
            expected: [text('The user retried'), chip(12), text(' twice.')],
        },
        {
            name: 'returns the plain text untouched when there is nothing to split',
            text: 'No citations here.',
            segments: [],
            expected: [text('No citations here.')],
        },
        {
            name: 'drops malformed entries and passes valid persisted segments through untouched',
            text: 'fallback text',
            segments: [text('Foo'), chip(12), { kind: 'chip' }, 'junk', null],
            expected: [text('Foo'), chip(12)],
        },
    ])('$name', ({ text: inputText, segments, expected }) => {
        expect(parseCitedSegments(inputText, segments)).toEqual(expected)
    })
})

describe('citedTextToPlainText', () => {
    it.each<{ name: string; text: string; segments: unknown; expected: string }>([
        {
            name: 'renders a leaked marker as a readable timestamp',
            text: 'The user retried (t 12) twice.',
            segments: undefined,
            expected: 'The user retried (00:12) twice.',
        },
        {
            name: 'splits comma-joined markers into one timestamp each',
            text: 'Clicked twice (t 39, t 57) before it responded',
            segments: [],
            expected: 'Clicked twice (00:39) (00:57) before it responded',
        },
        {
            name: 'serializes persisted chip segments',
            text: 'ignored when segments exist',
            segments: [
                { kind: 'text', value: 'Abandoned the cart' },
                { kind: 'chip', timestamp_ms: 161_000 },
                { kind: 'text', value: ' and left.' },
            ],
            expected: 'Abandoned the cart (02:41) and left.',
        },
        {
            name: 'keeps text without citations untouched',
            text: 'No citations here.',
            segments: [],
            expected: 'No citations here.',
        },
    ])('$name', ({ text, segments, expected }) => {
        expect(citedTextToPlainText(text, segments)).toBe(expected)
    })
})
