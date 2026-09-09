const GOAL_DRAFT_INTENT_KEY = 'replay-vision.goal-draft-intent'

/** One-shot hand-off of the in-player analysis nudge's goal to the creation wizard. The goal is
 * free text that can contain customer emails or names, so it travels via sessionStorage rather
 * than the URL, keeping it out of autocapture's $current_url, our own replay of our app, and
 * browser history. Only this channel auto-starts the AI draft, so a crafted external ?goal= link
 * can prefill the goal box but never spend the user's AI allowance on its own. */
export function markGoalDraftIntent(goal: string): void {
    try {
        sessionStorage.setItem(GOAL_DRAFT_INTENT_KEY, goal)
    } catch {
        // Storage can be unavailable (private mode); the nudge then just opens the wizard blank.
    }
}

/** Reads and clears the hand-off. The wizard must call this on every entry, whichever prefill
 * path wins, so a hand-off can never stay armed for the rest of the tab session and auto-start
 * a draft from a later, unrelated wizard visit. */
export function consumeGoalDraftIntent(): string | null {
    try {
        const goal = sessionStorage.getItem(GOAL_DRAFT_INTENT_KEY)
        sessionStorage.removeItem(GOAL_DRAFT_INTENT_KEY)
        return goal
    } catch {
        return null
    }
}
