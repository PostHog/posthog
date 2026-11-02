import { abortError } from '@/lib/abort'

/** One server-sent event. `event` defaults to `message` when the frame names none. */
export interface SseEvent {
    event: string
    data: string
    id?: string
}

export interface SseParser {
    feed: (chunk: string) => void
    reset: () => void
}

export function createSseParser(onEvent: (event: SseEvent) => void): SseParser {
    let buffer = ''
    let skipLeadingLf = false
    let event = ''
    let data: string[] = []
    let id: string | undefined

    const dispatch = (): void => {
        if (data.length > 0) {
            onEvent({ event: event || 'message', data: data.join('\n'), id })
        }
        event = ''
        data = []
        id = undefined
    }

    const handleLine = (line: string): void => {
        if (line === '') {
            dispatch()
            return
        }
        if (line.startsWith(':')) {
            return
        }
        const colon = line.indexOf(':')
        const field = colon === -1 ? line : line.slice(0, colon)
        let value = colon === -1 ? '' : line.slice(colon + 1)
        if (value.startsWith(' ')) {
            value = value.slice(1)
        }
        switch (field) {
            case 'event':
                event = value
                break
            case 'data':
                data.push(value)
                break
            case 'id':
                id = value
                break
            default:
                break
        }
    }

    return {
        feed: (chunk) => {
            if (!chunk) {
                return
            }
            // A CRLF split across chunks: the CR already ended the line, so this LF is not a blank line.
            buffer += skipLeadingLf && chunk.startsWith('\n') ? chunk.slice(1) : chunk
            skipLeadingLf = false
            let newline = buffer.search(/\r\n|\n|\r/)
            while (newline !== -1) {
                const line = buffer.slice(0, newline)
                const crAtEnd = buffer[newline] === '\r' && newline === buffer.length - 1
                buffer = buffer.slice(newline + (buffer[newline] === '\r' && buffer[newline + 1] === '\n' ? 2 : 1))
                skipLeadingLf = crAtEnd
                handleLine(line)
                newline = buffer.search(/\r\n|\n|\r/)
            }
        },
        reset: () => {
            buffer = ''
            skipLeadingLf = false
            event = ''
            data = []
            id = undefined
        },
    }
}

export async function readSse(
    response: Response,
    onEvent: (event: SseEvent) => void,
    signal?: AbortSignal
): Promise<void> {
    const body = response.body
    if (!body) {
        throw new Error('Streaming is not supported by this response')
    }
    // Expo installs `TextDecoder` on native. The check gives a clear error in a runtime without Expo's globals.
    if (typeof TextDecoder === 'undefined') {
        throw new Error('TextDecoder is not available in this runtime')
    }
    const parser = createSseParser(onEvent)
    const reader = body.getReader()
    const decoder = new TextDecoder()
    const abort = (): void => {
        void reader.cancel()
    }
    signal?.addEventListener('abort', abort, { once: true })
    try {
        while (true) {
            if (signal?.aborted) {
                throw abortError()
            }
            const { value, done } = await reader.read()
            if (done) {
                parser.feed(decoder.decode())
                break
            }
            parser.feed(decoder.decode(value, { stream: true }))
        }
    } finally {
        signal?.removeEventListener('abort', abort)
    }
}
