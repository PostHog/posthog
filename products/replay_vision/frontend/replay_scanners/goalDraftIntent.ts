const GOAL_DRAFT_INTENT_KEY = 'replay-vision.goal-draft-intent'

/** One-shot hand-off marker between the in-player analysis nudge and the creation wizard.
 * The wizard only auto-starts the AI draft for a ?goal= param when this marker is present, so a
 * crafted external link can prefill the goal box but never spend the user's AI allowance on its own. */
export function markGoalDraftIntent(): void {
    try {
        sessionStorage.setItem(GOAL_DRAFT_INTENT_KEY, '1')
    } catch {
        // Storage can be unavailable (private mode); the goal then just prefills without auto-start.
    }
}

export function consumeGoalDraftIntent(): boolean {
    try {
        const present = sessionStorage.getItem(GOAL_DRAFT_INTENT_KEY) !== null
        sessionStorage.removeItem(GOAL_DRAFT_INTENT_KEY)
        return present
    } catch {
        return false
    }
}
