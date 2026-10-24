import { createSseParser, readSse, type SseEvent } from './sse'

function parse(chunks: string[]): SseEvent[] {
    const events: SseEvent[] = []
    const parser = createSseParser((event) => events.push(event))
    for (const chunk of chunks) {
        parser.feed(chunk)
    }
    return events
}

describe('sse', () => {
    test.each<[string, string[], SseEvent[]]>([
        [
            'an unnamed frame defaults to message',
            ['data: {"a":1}\n\n'],
            [{ event: 'message', data: '{"a":1}', id: undefined }],
        ],
        [
            'a frame split across chunks',
            ['ev', 'ent: keepalive\nda', 'ta: {"type":"keep', 'alive"}\n', '\n'],
            [{ event: 'keepalive', data: '{"type":"keepalive"}', id: undefined }],
        ],
        [
            'ids attach to their frame',
            ['id: log-3\ndata: x\n\ndata: y\n\n'],
            [
                { event: 'message', data: 'x', id: 'log-3' },
                { event: 'message', data: 'y', id: undefined },
            ],
        ],
        ['CRLF line endings', ['id: 1-0\r\ndata: x\r\n\r\n'], [{ event: 'message', data: 'x', id: '1-0' }]],
        [
            'CRLF split between CR and LF keeps the id with its data',
            ['id: 1-0\r', '\ndata: x\r', '\n\r', '\n'],
            [{ event: 'message', data: 'x', id: '1-0' }],
        ],
        ['comment lines are ignored', [': ping\ndata: x\n\n'], [{ event: 'message', data: 'x', id: undefined }]],
        [
            'multi-line data joins with newlines',
            ['data: a\ndata: b\n\n'],
            [{ event: 'message', data: 'a\nb', id: undefined }],
        ],
        ['a frame without data dispatches nothing', ['event: end\n\n'], []],
        ['an unterminated frame waits for its blank line', ['data: x\n'], []],
    ])('%s', (_name, chunks, expected) => {
        expect(parse(chunks)).toEqual(expected)
    })

    test('readSse decodes a byte stream split mid-character', async () => {
        const bytes = new TextEncoder().encode('data: "Größe"\n\n')
        const chunks = [bytes.slice(0, 10), bytes.slice(10)]
        const reader = {
            read: jest.fn(async () => {
                const value = chunks.shift()
                return value ? { value, done: false } : { value: undefined, done: true }
            }),
            cancel: jest.fn(async () => undefined),
        }
        const response = { body: { getReader: () => reader } } as unknown as Response
        const events: SseEvent[] = []
        await readSse(response, (event) => events.push(event))
        expect(events).toEqual([{ event: 'message', data: '"Größe"', id: undefined }])
    })
})
