interface PendingBlock {
    resolve: (response: Response) => void
    reject: (error: Error) => void
    parts: string[]
    timer?: ReturnType<typeof setTimeout>
}

export class ReplayBlockBridge {
    private pending = new Map<number, PendingBlock>()
    private nextRequest = 0
    private failure: Error | null = null

    constructor(
        private post: (message: { type: 'block'; id: number; index: number }) => void,
        private timeoutMs = 30_000
    ) {}

    request(url: string): Promise<Response> {
        if (this.failure) return Promise.reject(this.failure)
        const match = /^\/__blocks\/(\d+)$/.exec(url)
        if (!match) return Promise.reject(new Error('Unsupported replay request'))
        const id = ++this.nextRequest
        return new Promise((resolve, reject) => {
            this.pending.set(id, { resolve, reject, parts: [] })
            this.setLoading(id, true)
            try {
                this.post({ type: 'block', id, index: Number(match[1]) })
            } catch {
                this.cancel()
            }
        })
    }

    setLoading(id: number, loading: boolean): void {
        const request = this.pending.get(id)
        if (!request) return
        clearTimeout(request.timer)
        request.timer = loading
            ? setTimeout(() => this.cancel(new Error('Replay block request timed out')), this.timeoutMs)
            : undefined
    }

    receive(id: number, text: string, done: boolean): void {
        const request = this.pending.get(id)
        if (!request) return
        request.parts.push(text)
        if (done) {
            clearTimeout(request.timer)
            this.pending.delete(id)
            request.resolve(new Response(request.parts.join('')))
            request.parts = []
        } else {
            this.setLoading(id, true)
        }
    }

    cancel(error = new Error('Replay block requests cancelled')): void {
        this.failure ??= error
        for (const request of this.pending.values()) {
            clearTimeout(request.timer)
            request.parts = []
            request.reject(this.failure)
        }
        this.pending.clear()
    }
}

interface ReplayWindowRange {
    windowId: number
    firstTimestamp: number
    lastTimestamp: number
}

interface ReplaySegment {
    windowId?: number | null
    startTimestamp: number
    endTimestamp: number
    isActive: boolean
}

export function replayWindowAt<T extends ReplayWindowRange>(
    windows: T[],
    segments: ReplaySegment[],
    timestamp: number
): T | undefined {
    let inactiveOwner: T | undefined
    for (const segment of segments) {
        if (timestamp < segment.startTimestamp || timestamp > segment.endTimestamp) continue
        const tab = windows.find((item) => item.windowId === segment.windowId)
        if (!tab) continue
        if (segment.isActive) return tab
        if (timestamp <= tab.lastTimestamp) inactiveOwner ??= tab
    }
    return (
        inactiveOwner ??
        windows.find((tab) => timestamp >= tab.firstTimestamp && timestamp <= tab.lastTimestamp) ??
        windows[windows.length - 1]
    )
}
