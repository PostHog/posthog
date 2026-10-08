/**
 * The title a rename should save, or `null` when there is nothing to save. The title field fires on every
 * blur whether or not the user typed, so most calls arrive with nothing to do.
 */
export function nextTaskTitle(input: string, currentTitle: string | undefined): string | null {
    const trimmed = input.trim()
    if (!trimmed || trimmed === currentTitle) {
        return null
    }
    return trimmed
}
