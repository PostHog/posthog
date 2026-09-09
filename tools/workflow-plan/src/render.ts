import type { Outcome, Scenario, WorkflowPlan } from './plan.ts'

export interface ScenarioPlan {
    scenario: Scenario
    plan: WorkflowPlan
}

const MARKS: Record<Outcome, string> = {
    success: 'RUN',
    failure: 'FAIL',
    cancelled: 'CANC',
    skipped: '.',
}

export function renderPlanTable(scenarioPlans: ScenarioPlan[]): string {
    const first = scenarioPlans[0]
    if (!first) {
        return ''
    }
    const jobIds = Object.keys(first.plan.jobs)
    const width = Math.max('job'.length, ...jobIds.map((id) => id.length))
    const lines = [
        `${'job'.padEnd(width)} ${scenarioPlans.map((_, index) => String(index + 1).padStart(4)).join(' ')}`,
        ...jobIds.map((jobId) => {
            const cells = scenarioPlans.map(({ plan }) => {
                const job = plan.jobs[jobId]
                const mark = job ? MARKS[job.result] : '?'
                const suffix = job?.matrixCells === 0 ? '0' : ''
                return `${mark}${suffix}`.padStart(4)
            })
            return `${jobId.padEnd(width)} ${cells.join(' ')}`
        }),
        '',
        ...scenarioPlans.map(({ scenario }, index) => `${index + 1}: ${scenario.name}`),
        '',
        'RUN runs, FAIL runs and fails, CANC cancelled, . skipped, 0 matrix expands to zero cells',
    ]
    const errors = scenarioPlans.flatMap(({ scenario, plan }) =>
        plan.errors.map(
            (error) =>
                `${scenario.name}: ${error.job}${error.step ? `/${error.step}` : ''} ${error.where}: ${error.message}`
        )
    )
    if (errors.length > 0) {
        lines.push('', 'Errors:', ...errors)
    }
    return lines.join('\n')
}

export function renderSteps(scenarioPlans: ScenarioPlan[], jobId: string): string {
    const first = scenarioPlans[0]
    const job = first?.plan.jobs[jobId]
    if (!first || !job) {
        return `no job named ${jobId}`
    }
    const labels = job.steps.map((step) => step.id ?? step.name ?? step.uses ?? `#${step.index}`)
    const width = Math.max('step'.length, ...labels.map((label) => label.length))
    const lines = [
        `${'step'.padEnd(width)} ${scenarioPlans.map((_, index) => String(index + 1).padStart(4)).join(' ')}`,
        ...job.steps.map((step, stepIndex) => {
            const cells = scenarioPlans.map(({ plan }) => {
                const planned = plan.jobs[jobId]?.steps[stepIndex]
                return (planned?.runs ? 'RUN' : '.').padStart(4)
            })
            return `${labels[stepIndex]!.padEnd(width)} ${cells.join(' ')}`
        }),
        '',
        ...scenarioPlans.map(({ scenario }, index) => `${index + 1}: ${scenario.name}`),
    ]
    return lines.join('\n')
}
