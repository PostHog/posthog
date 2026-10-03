import { appendStacktrace, fitStacktrace, MAX_ISSUE_BODY_LENGTH } from './externalIssueBody'

const TRACE = 'TypeError: boom\n  File "app.js", line: 3'

describe('appendStacktrace', () => {
    test.each([
        ['returns the text unchanged without a trace', 'PostHog issue: url', '', 'PostHog issue: url'],
        [
            'puts the trace after the text',
            'Details\n\nPostHog issue: url\n\n',
            TRACE,
            `Details\n\nPostHog issue: url\n\n\`\`\`\n${TRACE}\n\`\`\``,
        ],
        ['puts only the trace in an empty body', '', TRACE, `\`\`\`\n${TRACE}\n\`\`\``],
        [
            'uses a fence longer than any backtick run in the trace',
            'Details',
            'Error\n  const s = ```x```',
            'Details\n\n````\nError\n  const s = ```x```\n````',
        ],
    ])('%s', (_name, text, stacktrace, expected) => {
        expect(appendStacktrace(text, stacktrace)).toEqual(expected)
    })

    test.each([
        ['short text', 'PostHog issue: url'],
        ['text that leaves room for part of the trace', 'x'.repeat(MAX_ISSUE_BODY_LENGTH - 200)],
    ])('cuts a long trace at a line break so the body fits, with %s', (_name, text) => {
        const lines = Array.from({ length: 2000 }, (_, index) => `  File "app.js", line: ${index}, in: handler`)
        const stacktrace = lines.join('\n')
        const body = appendStacktrace(text, stacktrace)

        expect(body.length).toBeLessThanOrEqual(MAX_ISSUE_BODY_LENGTH)
        expect(body.startsWith(`${text}\n\n\`\`\`\n${lines[0]}`)).toBe(true)
        expect(body.endsWith(', in: handler\n...\n```')).toBe(true)
        // The dialog previews fitStacktrace, so it must be exactly the trace that goes into the body.
        expect(body).toEqual(`${text}\n\n\`\`\`\n${fitStacktrace(text, stacktrace)}\n\`\`\``)
    })

    test('leaves the trace out when the text leaves no room for it', () => {
        const text = 'x'.repeat(MAX_ISSUE_BODY_LENGTH)

        expect(appendStacktrace(text, TRACE)).toEqual(text)
        expect(fitStacktrace(text, TRACE)).toEqual('')
    })

    test('handles a trace with more backtick runs than a function call takes arguments', () => {
        const stacktrace = '`a'.repeat(200_000)

        expect(appendStacktrace('', stacktrace).startsWith('```\n`a`a')).toBe(true)
    })
})
