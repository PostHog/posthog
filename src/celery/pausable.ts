export interface Pausable {
    pause: () => Promise<void>
    resume: () => void
}
