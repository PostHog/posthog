import type { Outcome, Scenario, WorkflowPlan } from './plan.ts'

export interface ScenarioPlan {
    scenario: Scenario
    plan: WorkflowPlan
}

interface Column {
    name: string
    cells: string[]
}

/** Terminal-only decoration of the header row and every second data row. */
export interface TableStyle {
    header: (line: string) => string
    stripe: (line: string) => string
}

const MARKS: Record<Outcome, string> = {
    success: '▶',
    failure: '✗',
    cancelled: '⊘',
    skipped: '.',
}

const EMPTY_MATRIX_SUFFIX = '0'

const LEGEND = [
    [MARKS.success, 'runs'],
    [MARKS.failure, 'fails'],
    [MARKS.cancelled, 'cancelled'],
    [MARKS.skipped, 'skipped'],
    [EMPTY_MATRIX_SUFFIX, 'no matrix expansion'],
]
    .map(([mark, meaning]) => `${mark} = ${meaning}`)
    .join('   ')

function center(text: string, width: number): string {
    const left = Math.floor((width - text.length) / 2)
    return text.padStart(text.length + left).padEnd(width)
}

function renderGrid(cornerLabel: string, rowLabels: string[], columns: Column[], style?: TableStyle): string[] {
    const labelWidth = Math.max(cornerLabel.length, ...rowLabels.map((label) => label.length))
    const widths = columns.map(({ name, cells }) => Math.max(name.length, ...cells.map((cell) => cell.length)))
    const row = (label: string, cells: string[]): string =>
        `${label.padEnd(labelWidth)} ${cells.map((cell, index) => center(cell, widths[index]!)).join(' ')}`
    const decorate = (line: string, rowIndex: number): string =>
        style && rowIndex % 2 === 1 ? style.stripe(line) : line.trimEnd()
    const header = row(
        cornerLabel,
        columns.map(({ name }) => name)
    ).trimEnd()
    return [
        style ? style.header(header) : header,
        ...rowLabels.map((label, rowIndex) =>
            decorate(
                row(
                    label,
                    columns.map(({ cells }) => cells[rowIndex]!)
                ),
                rowIndex
            )
        ),
    ]
}

export function renderPlanTable(scenarioPlans: ScenarioPlan[], style?: TableStyle): string {
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
    const lines = [...renderGrid('job', jobIds, columns, style), '', LEGEND]
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

export function renderSteps(scenarioPlans: ScenarioPlan[], jobId: string, style?: TableStyle): string {
    const first = scenarioPlans[0]
    const job = first?.plan.jobs[jobId]
    if (!first || !job) {
        return `no job named ${jobId}`
    }
    const labels = job.steps.map((step) => step.id ?? step.name ?? step.uses ?? `#${step.index}`)
    const columns = scenarioPlans.map(({ scenario, plan }) => ({
        name: scenario.name,
        cells: job.steps.map((_, stepIndex) =>
            plan.jobs[jobId]?.steps[stepIndex]?.runs ? MARKS.success : MARKS.skipped
        ),
    }))
    return [...renderGrid('step', labels, columns, style), '', LEGEND].join('\n')
}
