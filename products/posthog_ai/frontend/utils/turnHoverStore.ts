/** The pointer crosses the gap between two rows of the same turn. The delay stops the reveal from flickering there. */
const LEAVE_DELAY_MS = 100

/**
 * Tracks which completed turn the pointer is over. A turn renders as several virtualized rows, so a CSS
 * `group-hover` cannot span it. Subscribers compare against their own turn id, so only the trailer whose
 * state changes re-renders.
 */
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

    leave(turnId: string): void {
        this.cancelClear()
        this.clearTimer = setTimeout(() => {
            this.clearTimer = null
            if (this.hoveredTurnId === turnId) {
                this.setHoveredTurnId(null)
            }
        }, LEAVE_DELAY_MS)
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
