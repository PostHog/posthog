import type { StoryFunnelStep } from './explainChartTypes'
import { mark } from './storyMarks'

function share(part: number, whole: number): string {
    const value = whole > 0 ? (part / whole) * 100 : 0
    return `${value > 0 && value < 10 ? Math.round(value * 10) / 10 : Math.round(value)}%`
}

// A step is the funnel's x-axis position, so it reads like a date on a trends chart, not like a highlighted cause.
function stepName(steps: StoryFunnelStep[], index: number): string {
    return mark('date', steps[index]?.name ?? `step ${index + 1}`)
}

function count(steps: StoryFunnelStep[], index: number, formatValue: (value: number) => string): string {
    return mark('value', formatValue(steps[index]?.count ?? 0))
}

/** The step with the smallest share of people who go on to the next one. */
function biggestDrop(steps: StoryFunnelStep[]): number | null {
    let worst: number | null = null
    for (let index = 0; index < steps.length - 1; index++) {
        const from = steps[index]!.count
        if (from <= 0) {
            continue
        }
        const kept = steps[index + 1]!.count / from
        if (worst === null || kept < steps[worst + 1]!.count / steps[worst]!.count) {
            worst = index
        }
    }
    return worst
}

export function funnelOverviewFacts(steps: StoryFunnelStep[], formatValue: (value: number) => string): string {
    if (steps.length < 2) {
        return ''
    }
    const last = steps.length - 1
    const sentences = [
        `${count(steps, 0, formatValue)} entered ${stepName(steps, 0)}, and ${count(steps, last, formatValue)} reached ${stepName(steps, last)}: ${mark('value', share(steps[last]!.count, steps[0]!.count))} of them.`,
    ]
    const drop = biggestDrop(steps)
    if (drop !== null && steps.length > 2) {
        sentences.push(
            `The biggest drop is from ${stepName(steps, drop)} to ${stepName(steps, drop + 1)}, where ${mark('value', share(steps[drop + 1]!.count, steps[drop]!.count))} go on.`
        )
    }
    return sentences.join(' ')
}

export function funnelChapterFacts(
    steps: StoryFunnelStep[],
    [start, end]: [number, number],
    formatValue: (value: number) => string
): string {
    if (start === end && start === 0) {
        return `${count(steps, 0, formatValue)} entered ${stepName(steps, 0)}.`
    }
    if (start === end) {
        return `${count(steps, end, formatValue)} reached ${stepName(steps, end)}: ${mark('value', share(steps[end]!.count, steps[end - 1]!.count))} of the ${formatValue(steps[end - 1]!.count)} at ${stepName(steps, end - 1)}.`
    }
    return `From ${stepName(steps, start)} to ${stepName(steps, end)}, ${mark('value', share(steps[end]!.count, steps[start]!.count))} go on: ${count(steps, start, formatValue)} to ${count(steps, end, formatValue)}.`
}
