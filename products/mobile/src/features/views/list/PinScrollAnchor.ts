export class PinScrollAnchor {
    private pending: string | null = null
    private completed: string | null = null
    private generation = 0
    private failed = false
    private measured = false

    get target(): string | null {
        return this.pending
    }

    get isMeasured(): boolean {
        return this.measured
    }

    get version(): number {
        return this.generation
    }

    start(target: string | null): void {
        this.generation++
        this.pending = target
        this.completed = null
        this.measured = false
    }

    recheck(): void {
        if (this.pending === null) this.pending = this.completed
    }

    cancel(): void {
        this.start(null)
    }

    measure(shortcutIds: readonly string[], version: number): void {
        if (version === this.generation && this.pending !== null && shortcutIds.includes(this.pending)) {
            this.measured = true
        }
    }

    fail(): void {
        this.failed = true
    }

    attempt(scroll: (target: string) => boolean): void {
        const target = this.pending
        if (target === null) return
        const generation = this.generation
        const measured = this.measured
        this.failed = false
        const sent = scroll(target)
        if (sent && measured && !this.failed && this.generation === generation) {
            this.completed = target
            this.pending = null
        }
    }
}

export function pinAnchorOffset(offset: number, delta: number, contentHeight: number, viewportHeight: number): number {
    return Math.max(0, Math.min(Math.max(0, contentHeight - viewportHeight), offset + delta))
}
