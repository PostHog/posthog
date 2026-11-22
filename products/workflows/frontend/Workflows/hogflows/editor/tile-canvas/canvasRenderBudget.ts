// The canvas renders every email step as the page draws, so a crafted workflow could stall it one step after another.
// Once rendering has taken this long within a second, later renders are skipped and their callers show plain text.
const RENDER_BUDGET_MS = 300
const budget = { windowStart: -Infinity, spent: 0 }

export function renderWithinBudget<T>(render: () => T): T | null {
    const started = Date.now()
    if (started - budget.windowStart > 1000) {
        budget.windowStart = started
        budget.spent = 0
    }
    if (budget.spent >= RENDER_BUDGET_MS) {
        return null
    }
    try {
        return render()
    } finally {
        budget.spent += Date.now() - started
    }
}
