export class RunStreamFrameBuffer<T> {
    private entries: T[] = []
    private frame: number | undefined
    private timer: ReturnType<typeof setTimeout> | undefined

    constructor(private readonly deliver: (entries: T[]) => void) {}

    push(entry: T): void {
        this.entries.push(entry)
        if (document.visibilityState === 'hidden' || this.entries.length >= 200) {
            this.flush()
        } else if (this.frame === undefined) {
            this.frame = requestAnimationFrame(() => this.flush())
            this.timer = setTimeout(() => this.flush(), 100)
        }
    }

    flush(): void {
        if (this.frame !== undefined) {
            cancelAnimationFrame(this.frame)
            this.frame = undefined
        }
        clearTimeout(this.timer)
        this.timer = undefined
        const entries = this.entries
        this.entries = []
        if (entries.length) {
            this.deliver(entries)
        }
    }
}
