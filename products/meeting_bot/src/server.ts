import { readFile } from 'node:fs/promises'
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { WebSocketServer } from 'ws'

import { PostHogAgent } from './agent'
import type { Config } from './config'
import { createBot, leaveCall, parseTranscriptEvent } from './recall'
import { SpeechSynthesizer } from './speech'
import { Stage } from './stage'
import { findTrigger, TranscriptBuffer } from './transcript'

const STAGE_HTML = join(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'stage.html')

/** How long to keep listening for the rest of a question when the trigger phrase ends an utterance. */
const CONTINUATION_WINDOW_MS = 6000
const MIN_PROMPT_WORDS = 3

interface PendingQuestion {
    speaker: string
    words: string
    startedAt: number
}

export function startServer(config: Config): Server {
    const agent = new PostHogAgent(config)
    const speech = new SpeechSynthesizer(config)
    const stage = new Stage()
    const buffer = new TranscriptBuffer(config.bufferSeconds)

    let pending: PendingQuestion | null = null
    let answering = false
    /**
     * Recall does not transcribe the bot's own audio, but other participants' microphones can pick it up
     * out of their speakers, which would otherwise let the bot re-trigger on its own answer.
     */
    let ignoreTriggersUntil = 0

    async function answer(question: string): Promise<void> {
        answering = true
        stage.send({ type: 'heard', question })
        stage.send({ type: 'thinking' })
        try {
            const result = await agent.ask({ question, context: buffer.context(Date.now()) })
            const { url } = await speech.synthesize(result.speech)
            // Hold the trigger lock until the page reports playback finished, with a ceiling in case it never does.
            ignoreTriggersUntil = Date.now() + 60_000
            stage.send({ type: 'answer', answer: result, audioUrl: url })
        } catch (error) {
            stage.send({
                type: 'error',
                message: error instanceof Error ? error.message : 'Something went wrong.',
            })
        } finally {
            answering = false
        }
    }

    function handleFinalUtterance(speaker: string, text: string): void {
        const now = Date.now()
        buffer.add({ speaker, text, at: now })

        if (pending && pending.speaker === speaker && now - pending.startedAt < CONTINUATION_WINDOW_MS) {
            const question = `${pending.words} ${text}`.trim()
            pending = null
            void answer(question)
            return
        }
        pending = null

        if (answering || now < ignoreTriggersUntil) {
            return
        }

        const match = findTrigger(text, config.triggerPhrase)
        if (!match) {
            return
        }

        // "Hey PostHog..." on its own is someone still drawing breath, so wait for the rest.
        if (match.prompt.split(/\s+/).filter(Boolean).length < MIN_PROMPT_WORDS) {
            pending = { speaker, words: match.prompt, startedAt: now }
            stage.send({ type: 'heard', question: match.prompt || 'Listening' })
            return
        }

        void answer(match.prompt)
    }

    const server = createServer((request: IncomingMessage, response: ServerResponse) => {
        void handleHttp(request, response)
    })

    async function handleHttp(request: IncomingMessage, response: ServerResponse): Promise<void> {
        const url = new URL(request.url ?? '/', `http://${request.headers.host ?? 'localhost'}`)

        if (url.pathname === '/healthz') {
            response.writeHead(200, { 'Content-Type': 'text/plain' })
            response.end('ok')
            return
        }

        if (url.pathname === '/stage' && request.method === 'GET') {
            if (url.searchParams.get('token') !== config.sharedSecret) {
                response.writeHead(403).end('Forbidden')
                return
            }
            const html = await readFile(STAGE_HTML, 'utf8')
            response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
            response.end(html)
            return
        }

        const audioMatch = url.pathname.match(/^\/audio\/([\w-]+)\.mp3$/)
        if (audioMatch && request.method === 'GET') {
            const clip = speech.take(audioMatch[1])
            if (!clip) {
                response.writeHead(404).end('Not found')
                return
            }
            response.writeHead(200, { 'Content-Type': 'audio/mpeg', 'Content-Length': clip.length })
            response.end(clip)
            return
        }

        if (url.pathname === '/bots' && request.method === 'POST') {
            const body = await readJson(request)
            const meetingUrl = typeof body.meeting_url === 'string' ? body.meeting_url : ''
            if (!meetingUrl) {
                response.writeHead(400, { 'Content-Type': 'application/json' })
                response.end(JSON.stringify({ error: 'meeting_url is required' }))
                return
            }
            try {
                const bot = await createBot(config, meetingUrl)
                response.writeHead(201, { 'Content-Type': 'application/json' })
                response.end(JSON.stringify(bot))
            } catch (error) {
                response.writeHead(502, { 'Content-Type': 'application/json' })
                response.end(JSON.stringify({ error: String(error) }))
            }
            return
        }

        const leaveMatch = url.pathname.match(/^\/bots\/([\w-]+)\/leave$/)
        if (leaveMatch && request.method === 'POST') {
            try {
                await leaveCall(config, leaveMatch[1])
                response.writeHead(204).end()
            } catch (error) {
                response.writeHead(502, { 'Content-Type': 'application/json' })
                response.end(JSON.stringify({ error: String(error) }))
            }
            return
        }

        response.writeHead(404).end('Not found')
    }

    const transcriptSockets = new WebSocketServer({ noServer: true })
    const stageSockets = new WebSocketServer({ noServer: true })

    transcriptSockets.on('connection', (socket) => {
        socket.on('message', (raw) => {
            const event = parseTranscriptEvent(raw.toString())
            if (!event) {
                return
            }
            if (event.isFinal) {
                handleFinalUtterance(event.speaker, event.text)
            } else {
                stage.send({ type: 'caption', speaker: event.speaker, text: event.text })
            }
        })
    })

    stageSockets.on('connection', (socket) => {
        stage.attach(socket, () => {
            ignoreTriggersUntil = Date.now() + 1500
            stage.send({ type: 'idle' })
        })
    })

    server.on('upgrade', (request, socket, head) => {
        const url = new URL(request.url ?? '/', `http://${request.headers.host ?? 'localhost'}`)
        if (url.searchParams.get('token') !== config.sharedSecret) {
            socket.write('HTTP/1.1 403 Forbidden\r\n\r\n')
            socket.destroy()
            return
        }

        if (url.pathname === '/recall/transcript') {
            transcriptSockets.handleUpgrade(request, socket, head, (ws) =>
                transcriptSockets.emit('connection', ws, request)
            )
            return
        }
        if (url.pathname === '/stage/socket') {
            stageSockets.handleUpgrade(request, socket, head, (ws) => stageSockets.emit('connection', ws, request))
            return
        }

        socket.destroy()
    })

    server.listen(config.port)
    return server
}

async function readJson(request: IncomingMessage): Promise<Record<string, unknown>> {
    const chunks: Buffer[] = []
    for await (const chunk of request) {
        chunks.push(chunk as Buffer)
    }
    if (chunks.length === 0) {
        return {}
    }
    try {
        return JSON.parse(Buffer.concat(chunks).toString('utf8')) as Record<string, unknown>
    } catch {
        return {}
    }
}
