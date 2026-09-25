import { Replayer } from 'posthog-js/rrweb'
import { EventType, IncrementalSource, MouseInteractions, eventWithTime } from 'posthog-js/rrweb-types'

import { COMMON_REPLAYER_CONFIG, getHrefFromSnapshot } from '@posthog/replay-shared'

export interface AnalysisClick {
    x: number
    y: number
    target: string
    timestamp: number
}

export interface AnalysisPageState {
    window_id: number
    timestamp: number
    visit_id: string
    width: number
    height: number
    signature: string[]
    clicks: AnalysisClick[]
    image: string
}

export interface ReplayAnalysisInput {
    url: string
    date_from: number
    date_to: number
    viewport_width: number
}

export interface ReplayAnalysisResult {
    states: AnalysisPageState[]
    excluded_clicks: number
    partial: boolean
}

export function matchesPage(url: string, target: string): boolean {
    return url.replace(/\/$/, '') === target.replace(/\/$/, '')
}

const nextFrame = (frames = 1): Promise<void> =>
    new Promise((resolve) => {
        const tick = (remaining: number): void => {
            requestAnimationFrame(() => (remaining <= 1 ? resolve() : tick(remaining - 1)))
        }
        tick(frames)
    })

function hash(value: string): string {
    let result = 2166136261
    for (let i = 0; i < value.length; i++) {
        result = Math.imul(result ^ value.charCodeAt(i), 16777619)
    }
    return (result >>> 0).toString(16)
}

function isExcluded(element: Element, view: Window, document: Document, verdicts: Map<Element, boolean>): boolean {
    const known = verdicts.get(element)
    if (known !== undefined) {
        return known
    }
    const style = view.getComputedStyle(element)
    const excluded =
        style.visibility === 'hidden' ||
        style.display === 'none' ||
        style.position === 'fixed' ||
        style.position === 'sticky' ||
        (element !== document.body &&
            element !== document.documentElement &&
            (element.scrollTop !== 0 || element.scrollLeft !== 0)) ||
        (!!element.parentElement && isExcluded(element.parentElement, view, document, verdicts))
    verdicts.set(element, excluded)
    return excluded
}

export function elementToken(
    element: Element,
    document: Document,
    verdicts: Map<Element, boolean> = new Map()
): string | null {
    const rect = element.getBoundingClientRect()
    const view = document.defaultView
    if (!view || element.ownerDocument !== document || rect.width < 8 || rect.height < 8) {
        return null
    }
    if (isExcluded(element, view, document, verdicts)) {
        return null
    }
    const geometry = [rect.x + view.scrollX, rect.y + view.scrollY, rect.width, rect.height].map((n) =>
        Math.round(n / 8)
    )
    const content =
        element.tagName === 'IMG'
            ? (element.getAttribute('src') ?? '')
            : ['BODY', 'H1', 'H2'].includes(element.tagName)
              ? (element.textContent ?? '').replace(/\s+/g, ' ').trim()
              : ''
    return `${element.tagName}:${geometry.join(':')}:${hash(content)}`
}

export class ReplayPageAnalyzer {
    private player: Replayer | null = null
    private windowId: number | null = null
    private host: HTMLDivElement

    private signature(doc: Document): string[] | null {
        const elements = Array.from(
            doc.querySelectorAll(
                'body,main,header,nav,footer,section,article,aside,h1,h2,h3,a,button,img,input,[role="dialog"]'
            )
        )
        if (elements.length > 500) {
            return null
        }
        const verdicts = new Map<Element, boolean>()
        return [
            ...new Set(
                elements
                    .map((element) => elementToken(element, doc, verdicts))
                    .filter((token): token is string => !!token)
            ),
        ].sort()
    }

    constructor(private windows: Record<number, eventWithTime[]>) {
        this.host = document.createElement('div')
        this.host.id = 'historical-heatmap-renderer'
        this.host.className = 'fixed top-0 left-0 z-[2147483647]'
        document.body.appendChild(this.host)
    }

    private async seek(windowId: number, timestamp: number): Promise<Document | null> {
        const events = this.windows[windowId]
        if (!events?.some((event) => event.type === EventType.FullSnapshot && event.timestamp <= timestamp)) {
            return null
        }
        if (this.windowId !== windowId || !this.player) {
            this.player?.destroy()
            this.host.replaceChildren()
            this.windowId = windowId
            this.player = new Replayer(events, {
                ...COMMON_REPLAYER_CONFIG,
                root: this.host,
                showWarning: false,
                showDebug: false,
                mouseTail: false,
                UNSAFE_replayCanvas: false,
            })
        }
        this.player.pause(Math.max(0, timestamp - events[0].timestamp))
        await nextFrame(2)
        const doc = this.player.iframe.contentDocument
        if (doc) {
            const deadline = performance.now() + 2000
            while (
                performance.now() < deadline &&
                (Array.from(doc.images).some((image) => !image.complete) ||
                    doc.fonts.status === 'loading' ||
                    Array.from(doc.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]')).some(
                        (link) => !link.sheet
                    ))
            ) {
                await nextFrame()
            }
        }
        return doc
    }

    async render(
        windowId: number,
        timestamp: number,
        expectedSignature?: string[],
        expectedHeight?: number
    ): Promise<boolean> {
        this.player?.destroy()
        this.player = null
        const doc = await this.seek(windowId, timestamp)
        if (!doc?.body) {
            return false
        }
        if (
            expectedSignature &&
            (JSON.stringify(this.signature(doc)) !== JSON.stringify(expectedSignature) ||
                doc.documentElement.scrollHeight !== expectedHeight)
        ) {
            return false
        }
        const style = doc.createElement('style')
        style.textContent = '* { animation-play-state: paused !important; transition: none !important; }'
        doc.head.appendChild(style)
        for (const element of Array.from(doc.querySelectorAll<HTMLElement>('*'))) {
            if (['fixed', 'sticky'].includes(doc.defaultView!.getComputedStyle(element).position)) {
                element.style.visibility = 'hidden'
            }
        }
        await this.scroll(0)
        return true
    }

    async scroll(y: number): Promise<number> {
        const view = this.player?.iframe.contentWindow
        view?.scrollTo({ top: y, left: 0, behavior: 'instant' })
        await nextFrame(2)
        return view?.scrollY ?? 0
    }

    destroy(): void {
        this.player?.destroy()
        this.host.remove()
    }

    async analyze(input: ReplayAnalysisInput): Promise<ReplayAnalysisResult> {
        const result: ReplayAnalysisResult = { states: [], excluded_clicks: 0, partial: false }
        let inspected = 0
        for (const [windowIdText, events] of Object.entries(this.windows)) {
            const windowId = Number(windowIdText)
            let url = ''
            let width = 0
            let visit = ''
            let lastSample = 0
            const states = new Map<string, AnalysisPageState>()
            for (const event of events) {
                const href = getHrefFromSnapshot(event)
                if (href) {
                    if (href !== url || (event.type === EventType.Custom && event.data.tag === '$pageview')) {
                        visit = `${windowId}:${event.timestamp}`
                    }
                    url = href
                }
                if (event.type === EventType.Meta) {
                    width = event.data.width
                } else if (
                    event.type === EventType.IncrementalSnapshot &&
                    event.data.source === IncrementalSource.ViewportResize
                ) {
                    width = event.data.width
                }
                if (
                    event.timestamp < input.date_from ||
                    event.timestamp >= input.date_to ||
                    !matchesPage(url, input.url)
                ) {
                    continue
                }
                const click =
                    event.type === EventType.IncrementalSnapshot &&
                    event.data.source === IncrementalSource.MouseInteraction &&
                    event.data.type === MouseInteractions.Click
                        ? event.data
                        : null
                const exclude = (partial = false): void => {
                    result.partial ||= partial
                    result.excluded_clicks += click ? 1 : 0
                }
                if (Math.abs(width - input.viewport_width) > 16) {
                    exclude()
                    continue
                }
                if (!click && event.timestamp - lastSample < 5000) {
                    continue
                }
                if (++inspected > 100 || result.states.length >= 20) {
                    exclude(true)
                    continue
                }
                lastSample = event.timestamp
                const momentTimestamp = event.timestamp - (click ? 1 : 0)
                const doc = await this.seek(windowId, Math.max(events[0].timestamp, momentTimestamp))
                if (!doc?.body || !doc.body.childElementCount || !this.player) {
                    exclude()
                    continue
                }
                const height = doc.documentElement.scrollHeight
                if (height > 20000 || height <= 0 || doc.documentElement.innerHTML.length > 2_000_000) {
                    exclude(true)
                    continue
                }
                const signature = this.signature(doc)
                if (!signature) {
                    exclude(true)
                    continue
                }
                if (!signature.length) {
                    exclude()
                    continue
                }
                const identity = `${visit}:${width}:${height}:${signature.join('|')}`
                let state = states.get(identity)
                if (!state) {
                    state = {
                        window_id: windowId,
                        timestamp: momentTimestamp,
                        visit_id: visit,
                        width,
                        height,
                        signature,
                        clicks: [],
                        image: '',
                    }
                    states.set(identity, state)
                    result.states.push(state)
                }
                if (click) {
                    const target = this.player.getMirror().getNode(click.id)
                    let element = target?.nodeType === 1 ? (target as Element) : target?.parentElement
                    let token = element ? elementToken(element, doc) : null
                    if (!element || ['CANVAS', 'VIDEO', 'IFRAME'].includes(element.tagName) || !token) {
                        result.excluded_clicks++
                        continue
                    }
                    const targetBounds = element.getBoundingClientRect()
                    if (
                        click.x === undefined ||
                        click.y === undefined ||
                        click.x < targetBounds.left - 4 ||
                        click.x > targetBounds.right + 4 ||
                        click.y < targetBounds.top - 4 ||
                        click.y > targetBounds.bottom + 4
                    ) {
                        result.excluded_clicks++
                        continue
                    }
                    while (element && element !== doc.body && (!token || !signature.includes(token))) {
                        element = element.parentElement ?? undefined
                        token = element ? elementToken(element, doc) : null
                    }
                    const x = click.x + (doc.defaultView?.scrollX ?? 0)
                    const y = click.y + (doc.defaultView?.scrollY ?? 0)
                    if (
                        element !== doc.body &&
                        token &&
                        signature.includes(token) &&
                        x >= 0 &&
                        x <= width &&
                        y >= 0 &&
                        y <= height &&
                        state.clicks.length < 1000
                    ) {
                        state.clicks.push({ x, y, target: token, timestamp: event.timestamp })
                    } else {
                        result.excluded_clicks++
                    }
                }
            }
        }
        return result
    }
}
