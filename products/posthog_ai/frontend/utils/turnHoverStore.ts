/** The pointer crosses the gap between two rows of the same turn. The delay stops the reveal from flickering there. */
const LEAVE_DELAY_MS = 100

/** A turn renders as several virtualized rows, so CSS `group-hover` cannot span it and `useState` would re-render every row. */
export class TurnHoverStore {
    private hoveredTurnId: string | null = null
    private clearTimer: ReturnType<typeof setTimeout> | null = null
    private readonly listeners = new Set<() => void>()

    subscribe = (listener: () => void): (() => void) => {
        this.listeners.add(listener)
        return () => {
            this.listeners.delete(listener)
        }
    }

    getHoveredTurnId = (): string | null => this.hoveredTurnId

    enter(turnId: string): void {
        this.cancelClear()
        this.setHoveredTurnId(turnId)
    }

    leave(): void {
        this.cancelClear()
        this.clearTimer = setTimeout(() => this.setHoveredTurnId(null), LEAVE_DELAY_MS)
    }

    private cancelClear(): void {
        if (this.clearTimer !== null) {
            clearTimeout(this.clearTimer)
            this.clearTimer = null
        }
    }

    private setHoveredTurnId(turnId: string | null): void {
        if (this.hoveredTurnId === turnId) {
            return
        }
        this.hoveredTurnId = turnId
        this.listeners.forEach((listener) => listener())
    }
}
