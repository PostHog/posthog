import type { VideoPlayer, VideoPlayerEvents } from 'expo-video'

import { fetchSnapshotBlocks, fetchSnapshotRange, type SnapshotBlock } from '@/api/snapshots'
import type { DemoReplaySnapshots } from '@/demo/replays'
import { actionErrorMessage } from '@/lib/errors'
import { FEED_PERF, perfMark } from '../feed/feedPerf'
import type { FeedPlayer } from '../feed/feedPlayer'
import { commandScript, type PhoneHostCommand, type PhonePlayerMessage, parsePlayerMessage } from './phoneProtocol'

let perfPlayers = 0

/** Text goes into the page in pieces, so one `injectJavaScript` call never carries a whole block range. */
const CHUNK_CHARACTERS = 512 * 1024

export interface PageHandle {
    inject: (script: string) => void
}

export interface PlaybackMark {
    name: string
    /** Milliseconds since the player was created until its first frame, then since the last `prepare`. */
    ms: number
    detail?: Record<string, number | string>
}

type Listener = (payload: { currentTime: number }) => void
type EmittedEvent = 'timeUpdate' | 'playToEnd' | 'statusChange'

/**
 * Plays one recording in a WebView page (`ReplayWebView`) with the same surface as an `expo-video` player, on the
 * session clock: `currentTime` is seconds since the recording's start. The app fetches the snapshot blocks with its
 * own credentials and hands the page their text; the page never sees a token.
 */
export class WebReplayPlayer implements FeedPlayer {
    status: FeedPlayer['status'] = 'idle'
    playing = false
    errorMessage: string | null = null
    marks: PlaybackMark[] = []
    private time = 0
    private rate = 1
    private skipInactivity = true
    private listeners = new Map<keyof VideoPlayerEvents, Set<Listener>>()
    private firstFrameListeners = new Set<() => void>()
    private page: PageHandle | null = null
    private pageLoaded = false
    private initSent = false
    private blocks: SnapshotBlock[] | null = null
    private listingError: string | null = null
    private queue: PhoneHostCommand[] = []
    private controller = new AbortController()
    private rangeController = new AbortController()
    private preparedKey: string | null = null
    private preparedAt = Date.now()
    private framed = false
    private awaitingTime = false
    /** Tells players apart in timing marks; two moment cards of one recording each have a player. */
    readonly perfId = ++perfPlayers

    constructor(
        readonly sessionId: string,
        private readonly startMs: number,
        private readonly demoSnapshots?: DemoReplaySnapshots
    ) {
        void this.loadBlocks()
    }

    get currentTime(): number {
        return this.time
    }

    set currentTime(seconds: number) {
        this.time = seconds
        this.send({ type: 'seek', ts: this.startMs + seconds * 1000 })
    }

    get playbackRate(): number {
        return this.rate
    }

    set playbackRate(rate: number) {
        if (rate !== this.rate) {
            this.rate = rate
            this.send({ type: 'speed', speed: rate })
        }
    }

    setSkipInactivity(on: boolean): void {
        if (on !== this.skipInactivity) {
            this.skipInactivity = on
            this.send({ type: 'skipInactivity', on })
        }
    }

    play(): void {
        if (!this.playing) {
            this.mark('playRequested')
        }
        this.playing = true
        this.send({ type: 'play' })
    }

    pause(): void {
        this.playing = false
        this.send({ type: 'pause' })
    }

    /** Loads the blocks around `startSeconds` and builds the page there; plays when `play` is true. */
    prepare(startSeconds: number, endSeconds: number | null, play: boolean): void {
        const key = `${startSeconds}:${endSeconds}`
        if (key === this.preparedKey) {
            return
        }
        if (this.framed) {
            this.preparedAt = Date.now()
            this.marks = []
        }
        this.preparedKey = key
        this.time = startSeconds
        this.playing = play
        this.mark('prepare', { startSeconds })
        this.setStatus(this.listingError ? 'error' : 'loading')
        this.send({
            type: 'prepare',
            targetTs: this.startMs + startSeconds * 1000,
            endTs: endSeconds === null ? null : this.startMs + endSeconds * 1000,
            play,
        })
    }

    /**
     * Moves the end of the window and keeps playing from the current time, with no rebuild. A reload after a crash
     * starts again from the current time with the new end.
     */
    setWindow(endSeconds: number | null): void {
        this.preparedKey = `${this.time}:${endSeconds}`
        this.send({ type: 'window', endTs: endSeconds === null ? null : this.startMs + endSeconds * 1000 })
    }

    /** Emits `timeUpdate`, `playToEnd` and `statusChange`, each with `{ currentTime }` only. */
    addListener<EventName extends keyof VideoPlayerEvents>(
        eventName: EventName,
        listener: VideoPlayerEvents[EventName]
    ): ReturnType<VideoPlayer['addListener']> {
        const set = this.listeners.get(eventName) ?? new Set<Listener>()
        this.listeners.set(eventName, set)
        set.add(listener as unknown as Listener)
        return {
            remove: () => {
                set.delete(listener as unknown as Listener)
            },
        }
    }

    onFirstFrame(listener: () => void): { remove: () => void } {
        this.firstFrameListeners.add(listener)
        return { remove: () => this.firstFrameListeners.delete(listener) }
    }

    attach(page: PageHandle): void {
        this.page = page
        this.pageLoaded = false
        this.initSent = false
    }

    detach(page: PageHandle): void {
        if (this.page === page) {
            this.page = null
            this.pageLoaded = false
            this.initSent = false
        }
    }

    destroy(): void {
        this.controller.abort()
        this.rangeController.abort()
        this.listeners.clear()
        this.firstFrameListeners.clear()
        this.page = null
    }

    restart(): void {
        this.rangeController.abort()
        this.rangeController = new AbortController()
        this.pageLoaded = false
        this.initSent = false
        this.queue = []
        this.prepareAgain(this.time)
    }

    /**
     * Try again after a load error. The page is still alive and does not send `loaded` again, so it gets the prepare
     * at once and asks again for the ranges that failed. A failed listing is fetched again first.
     */
    retry(): void {
        this.errorMessage = null
        if (this.listingError) {
            this.listingError = null
            void this.loadBlocks()
        }
        this.prepareAgain()
    }

    private prepareAgain(resumeAt?: number): void {
        const key = this.preparedKey
        this.preparedKey = null
        if (key) {
            const [start, end] = key.split(':')
            this.prepare(resumeAt ?? Number(start), end === 'null' ? null : Number(end), this.playing)
        }
    }

    onPageMessage(raw: string): void {
        const message = parsePlayerMessage(raw, this.blocks?.length ?? 0)
        if (message) {
            this.handle(message)
        }
    }

    private handle(message: PhonePlayerMessage): void {
        switch (message.type) {
            case 'loaded':
                this.mark('pageLoaded')
                this.pageLoaded = true
                this.flush()
                return
            case 'need':
                void this.loadRange(message.requestId, message.from, message.to)
                return
            case 'status':
                if (FEED_PERF) {
                    perfMark(`player:status:${message.status}`, Date.now(), {
                        session: this.sessionId.slice(-6),
                        player: this.perfId,
                    })
                }
                if (message.status === 'error') {
                    this.errorMessage = message.message ?? null
                }
                this.setStatus(message.status)
                return
            case 'time':
                if (FEED_PERF && this.awaitingTime && message.playing) {
                    this.awaitingTime = false
                    perfMark('player:time', Date.now(), {
                        session: this.sessionId.slice(-6),
                        player: this.perfId,
                        t: Math.round(message.ts - this.startMs),
                    })
                }
                this.time = Math.max(0, (message.ts - this.startMs) / 1000)
                this.playing = message.playing
                this.emit('timeUpdate', { currentTime: this.time })
                return
            case 'firstFrame':
                this.framed = true
                for (const listener of this.firstFrameListeners) {
                    listener()
                }
                return
            case 'ended':
                this.playing = false
                this.emit('playToEnd', { currentTime: this.time })
                return
            case 'mark':
                if (FEED_PERF) {
                    perfMark(`page:${message.name}`, message.at, {
                        session: this.sessionId.slice(-6),
                        player: this.perfId,
                    })
                }
                this.mark(message.name, { ...message.detail, pageAt: message.at - this.preparedAt })
                if (message.name === 'firstFrame') {
                    this.report()
                }
                return
            case 'log':
                if (__DEV__) {
                    console.warn(`[replay-web] ${this.sessionId} ${message.message}`)
                }
                return
        }
    }

    private setStatus(status: FeedPlayer['status']): void {
        if (status !== this.status) {
            this.status = status
            this.emit('statusChange', { currentTime: this.time })
        }
    }

    private emit(eventName: EmittedEvent, payload: { currentTime: number }): void {
        for (const listener of this.listeners.get(eventName) ?? []) {
            listener(payload)
        }
    }

    private mark(name: string, detail?: Record<string, number | string>): void {
        this.marks.push({ name, ms: Date.now() - this.preparedAt, detail })
    }

    private report(): void {
        if (__DEV__) {
            console.log(`[replay-web] ${JSON.stringify({ sessionId: this.sessionId, marks: this.marks })}`)
        }
    }

    private send(command: PhoneHostCommand): void {
        if (FEED_PERF && command.type !== 'blocks' && command.type !== 'speed' && command.type !== 'skipInactivity') {
            perfMark(`player:${command.type}`, Date.now(), { session: this.sessionId.slice(-6), player: this.perfId })
            this.awaitingTime = true
        }
        if (!this.page || !this.pageLoaded || !this.initSent) {
            this.queue =
                command.type === 'prepare'
                    ? [...this.queue.filter((item) => item.type !== 'prepare'), command]
                    : [...this.queue, command]
            this.flush()
            return
        }
        this.page.inject(commandScript(command))
    }

    private flush(): void {
        if (!this.page || !this.pageLoaded || !this.blocks?.length) {
            return
        }
        if (!this.initSent) {
            this.page.inject(
                commandScript({
                    type: 'init',
                    sessionId: this.sessionId,
                    sources: this.blocks.map(({ startTs, endTs }) => ({ startTs, endTs })),
                    speed: this.rate,
                    skipInactivity: this.skipInactivity,
                })
            )
            this.initSent = true
        }
        const queued = this.queue
        this.queue = []
        for (const command of queued) {
            this.page.inject(commandScript(command))
        }
    }

    private async loadBlocks(): Promise<void> {
        this.mark('listRequested')
        try {
            const blocks = this.demoSnapshots
                ? [this.demoSnapshots.block]
                : await fetchSnapshotBlocks(this.sessionId, this.controller.signal)
            this.mark('listReceived', { blocks: blocks.length })
            if (blocks.length === 0) {
                this.setListingError('This recording has no playback data yet.')
                return
            }
            this.blocks = blocks
            this.flush()
        } catch (error) {
            if (!this.controller.signal.aborted) {
                this.setListingError(actionErrorMessage(error))
            }
        }
    }

    private setListingError(message: string): void {
        this.listingError = message
        this.errorMessage = message
        this.setStatus('error')
    }

    private async loadRange(requestId: number, from: number, to: number): Promise<void> {
        const { signal } = this.rangeController
        this.mark('rangeRequested', { from, to })
        try {
            const text = this.demoSnapshots?.text ?? (await fetchSnapshotRange(this.sessionId, from, to, signal))
            this.mark('rangeReceived', { chars: text.length })
            const page = this.page
            if (!page || signal.aborted) {
                return
            }
            for (let offset = 0; offset < text.length || offset === 0; offset += CHUNK_CHARACTERS) {
                const done = offset + CHUNK_CHARACTERS >= text.length
                page.inject(
                    commandScript({
                        type: 'blocks',
                        requestId,
                        text: text.slice(offset, offset + CHUNK_CHARACTERS),
                        done,
                    })
                )
            }
            this.mark('handedOff')
        } catch (error) {
            if (!signal.aborted) {
                this.page?.inject(
                    commandScript({ type: 'blocksFailed', requestId, message: actionErrorMessage(error) })
                )
            }
        }
    }
}
