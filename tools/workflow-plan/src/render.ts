import type { Outcome, Scenario, WorkflowPlan } from './plan.ts'

export interface ScenarioPlan {
    scenario: Scenario
    plan: WorkflowPlan
}

interface Column {
    name: string
    cells: string[]
}

const MARKS: Record<Outcome, string> = {
    success: 'RUN',
    failure: 'FAIL',
    cancelled: 'CANC',
    skipped: '.',
}

const EMPTY_MATRIX_SUFFIX = '0'
const EMPTY_MATRIX_NOTE = `A trailing ${EMPTY_MATRIX_SUFFIX} marks a job whose matrix expands to zero cells.`

function renderGrid(cornerLabel: string, rowLabels: string[], columns: Column[]): string[] {
    const labelWidth = Math.max(cornerLabel.length, ...rowLabels.map((label) => label.length))
    const widths = columns.map(({ name, cells }) => Math.max(name.length, ...cells.map((cell) => cell.length)))
    const row = (label: string, cells: string[]): string =>
        `${label.padEnd(labelWidth)} ${cells.map((cell, index) => cell.padStart(widths[index]!)).join(' ')}`
    return [
        row(
            cornerLabel,
            columns.map(({ name }) => name)
        ),
        ...rowLabels.map((label, rowIndex) =>
            row(
                label,
                columns.map(({ cells }) => cells[rowIndex]!)
            )
        ),
    ]
}

export function renderPlanTable(scenarioPlans: ScenarioPlan[]): string {
    const first = scenarioPlans[0]
    if (!first) {
        return ''
    }
    const jobIds = Object.keys(first.plan.jobs)
    const columns = scenarioPlans.map(({ scenario, plan }) => ({
        name: scenario.name,
        cells: jobIds.map((jobId) => {
            const job = plan.jobs[jobId]
            if (!job) {
                return '?'
            }
            return job.matrixCells === 0 ? `${MARKS[job.result]}${EMPTY_MATRIX_SUFFIX}` : MARKS[job.result]
        }),
    }))
    const lines = renderGrid('job', jobIds, columns)
    const hasEmptyMatrix = scenarioPlans.some(({ plan }) =>
        Object.values(plan.jobs).some((job) => job.matrixCells === 0)
    )
    if (hasEmptyMatrix) {
        lines.push('', EMPTY_MATRIX_NOTE)
    }
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
    const columns = scenarioPlans.map(({ scenario, plan }) => ({
        name: scenario.name,
        cells: job.steps.map((_, stepIndex) => (plan.jobs[jobId]?.steps[stepIndex]?.runs ? 'RUN' : '.')),
    }))
    return renderGrid('step', labels, columns).join('\n')
}
