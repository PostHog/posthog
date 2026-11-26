import type { FunnelStepsExplainChartData, StoryFunnelStep } from './explainChartTypes'
import { mark } from './storyMarks'

export interface FunnelFactsStep extends StoryFunnelStep {
    optional: boolean
}

export function funnelFactsSteps(data: FunnelStepsExplainChartData): FunnelFactsStep[] {
    return data.steps.map((step, index) => ({
        ...step,
        optional: data.query.series?.[index]?.optionalInFunnel === true,
    }))
}

function share(part: number, whole: number): string {
    const value = whole > 0 ? (part / whole) * 100 : 0
    return `${value > 0 && value < 10 ? Math.round(value * 10) / 10 : Math.round(value)}%`
}

// A step is the funnel's x-axis position, so it reads like a date on a trends chart, not like a highlighted cause.
function stepName(steps: FunnelFactsStep[], index: number): string {
    return mark('date', steps[index]?.name ?? `step ${index + 1}`)
}

function count(steps: FunnelFactsStep[], index: number, formatValue: (value: number) => string): string {
    return mark('value', formatValue(steps[index]?.count ?? 0))
}

// People can skip an optional step, so the steps after it convert from the last required step.
function requiredStepAt(steps: FunnelFactsStep[], index: number): number {
    let required = index
    while (required > 0 && steps[required]!.optional) {
        required--
    }
    return required
}

/** The two required steps with the smallest share of people who go on from one to the next. */
function biggestDrop(steps: FunnelFactsStep[]): [number, number] | null {
    let worst: [number, number] | null = null
    let worstKept = Infinity
    for (let to = 1; to < steps.length; to++) {
        const from = requiredStepAt(steps, to - 1)
        if (steps[to]!.optional || steps[from]!.count <= 0) {
            continue
        }
        const kept = steps[to]!.count / steps[from]!.count
        if (kept < worstKept) {
            worst = [from, to]
            worstKept = kept
        }
    }
    return worst
}

export function funnelOverviewFacts(steps: FunnelFactsStep[], formatValue: (value: number) => string): string {
    if (steps.length < 2) {
        return ''
    }
    const last = steps.length - 1
    const sentences = [
        `${count(steps, 0, formatValue)} entered ${stepName(steps, 0)}, and ${count(steps, last, formatValue)} reached ${stepName(steps, last)}: ${mark('value', share(steps[last]!.count, steps[0]!.count))} of them.`,
    ]
    const drop = biggestDrop(steps)
    if (drop !== null && steps.filter((step) => !step.optional).length > 2) {
        const [from, to] = drop
        sentences.push(
            `The biggest drop is from ${stepName(steps, from)} to ${stepName(steps, to)}, where ${mark('value', share(steps[to]!.count, steps[from]!.count))} go on.`
        )
    }
    return sentences.join(' ')
}

export function funnelChapterFacts(
    steps: FunnelFactsStep[],
    [start, end]: [number, number],
    formatValue: (value: number) => string
): string {
    if (start === end && start === 0) {
        return `${count(steps, 0, formatValue)} entered ${stepName(steps, 0)}.`
    }
    if (start === end) {
        const from = requiredStepAt(steps, end - 1)
        return `${count(steps, end, formatValue)} reached ${stepName(steps, end)}: ${mark('value', share(steps[end]!.count, steps[from]!.count))} of the ${formatValue(steps[from]!.count)} at ${stepName(steps, from)}.`
    }
    const from = requiredStepAt(steps, start)
    return `From ${stepName(steps, from)} to ${stepName(steps, end)}, ${mark('value', share(steps[end]!.count, steps[from]!.count))} go on: ${count(steps, from, formatValue)} to ${count(steps, end, formatValue)}.`
}
