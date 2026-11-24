import type { KpiDelta } from './promptReport'

/** `change` is in rate units (0.012 is 1.2 percentage points). A page is cited in a small share of the answers, so
 *  the label keeps one decimal, and a change too small to show keeps its direction. */
export const moverDelta = (change: number, days: number): KpiDelta => {
    const points = Math.round(Math.abs(change) * 1000) / 10
    const sign = change > 0 ? '+' : '-'
    return {
        label: change === 0 ? 'No change' : points === 0 ? '<0.1 pts' : `${sign}${points} pts`,
        direction: change === 0 ? 'flat' : change > 0 ? 'up' : 'down',
        tooltip: `Change against the ${days} days before, in percentage points`,
    }
}
