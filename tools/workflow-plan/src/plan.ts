import { load } from 'js-yaml'
import { readFileSync } from 'node:fs'

import {
    type Context,
    type FunctionMap,
    type JsonValue,
    evaluateCondition,
    evaluateTemplate,
    evaluateValue,
    planFunctions,
} from './expressions.ts'

export type Outcome = 'success' | 'failure' | 'cancelled' | 'skipped'

export interface StepStub {
    outputs?: Record<string, string>
    outcome?: Outcome
}

export interface Scenario {
    name: string
    github: Context
    vars?: Record<string, string>
    /** Stubbed step results by job id, then step id (or name). Steps the plan skips lose their stubbed outputs. */
    steps?: Record<string, Record<string, StepStub>>
    /** Overrides a job's evaluated outputs, for reusable-workflow calls and script-driven outputs. */
    jobOutputs?: Record<string, Record<string, string>>
    /** The run was cancelled before any job started, except those in `completedBeforeCancel`. */
    cancelled?: boolean
    completedBeforeCancel?: readonly string[]
}

export interface RawStep {
    id?: string
    name?: string
    if?: unknown
    uses?: string
    run?: string
    env?: Record<string, unknown>
    with?: Record<string, unknown>
    'continue-on-error'?: unknown
    parallel?: RawStep[]
}

export interface RawJob {
    name?: string
    if?: unknown
    needs?: string | string[]
    uses?: string
    env?: Record<string, unknown>
    outputs?: Record<string, unknown>
    steps?: RawStep[]
    strategy?: { matrix?: unknown }
}

export interface Workflow {
    name?: string
    on?: unknown
    env?: Record<string, unknown>
    jobs: Record<string, RawJob>
}

export interface StepPlan {
    index: number
    id: string | undefined
    name: string | undefined
    uses: string | undefined
    runs: boolean
}

export interface JobPlan {
    id: string
    result: Outcome
    outputs: Record<string, string>
    steps: StepPlan[]
    /** Number of matrix cells the job expands to; undefined when there is no matrix or it could not be evaluated. */
    matrixCells: number | undefined
}

export interface PlanError {
    job: string
    step?: string
    where: 'if' | 'env' | 'outputs' | 'matrix'
    message: string
}

export interface WorkflowPlan {
    jobs: Record<string, JobPlan>
    errors: PlanError[]
}

interface StepContext {
    outputs: Record<string, string>
    outcome: Outcome
    conclusion: Outcome
}

export function parseWorkflow(source: string): Workflow {
    const parsed = load(source)
    if (typeof parsed !== 'object' || parsed === null || typeof (parsed as Workflow).jobs !== 'object') {
        throw new Error('workflow has no jobs')
    }
    return parsed as Workflow
}

export function loadWorkflow(path: string): Workflow {
    return parseWorkflow(readFileSync(path, 'utf8'))
}

export function flattenSteps(steps: RawStep[] | undefined): RawStep[] {
    return (steps ?? []).flatMap((step) => (Array.isArray(step.parallel) ? flattenSteps(step.parallel) : [step]))
}

function needIds(job: RawJob): string[] {
    if (job.needs === undefined) {
        return []
    }
    return Array.isArray(job.needs) ? job.needs : [job.needs]
}

function jobOrder(jobs: Record<string, RawJob>): string[] {
    const order: string[] = []
    const seen = new Set<string>()
    const visit = (id: string): void => {
        if (seen.has(id) || !(id in jobs)) {
            return
        }
        seen.add(id)
        for (const need of needIds(jobs[id]!)) {
            visit(need)
        }
        order.push(id)
    }
    Object.keys(jobs).forEach(visit)
    return order
}

function evaluateEnv(
    raw: Record<string, unknown> | undefined,
    context: Context,
    functions: FunctionMap
): Record<string, string> {
    const env: Record<string, string> = {}
    for (const [key, value] of Object.entries(raw ?? {})) {
        env[key] = evaluateTemplate(value, context, functions)
    }
    return env
}

export function countMatrixCells(rawMatrix: unknown, context: Context, functions: FunctionMap): number | undefined {
    if (rawMatrix === undefined || rawMatrix === null) {
        return undefined
    }
    const matrix = evaluateValue(rawMatrix, context, functions)
    if (Array.isArray(matrix)) {
        return matrix.length
    }
    if (typeof matrix !== 'object' || matrix === null) {
        return undefined
    }
    const entries = matrix as Record<string, unknown>
    const include = evaluateValue(entries['include'], context, functions)
    if (include === null) {
        return undefined
    }
    const includeCount = Array.isArray(include) ? include.length : 0
    const axes = Object.entries(entries)
        .filter(([key]) => key !== 'include' && key !== 'exclude')
        .map(([, value]) => evaluateValue(value, context, functions))
    if (axes.some((value) => value === null)) {
        return undefined
    }
    const axisSizes = axes.map((value) => (Array.isArray(value) ? value.length : 1))
    if (axisSizes.length === 0) {
        return includeCount
    }
    return axisSizes.reduce((product, size) => product * size, 1) + includeCount
}

function toStepPlan(step: RawStep, index: number, runs: boolean): StepPlan {
    return { index, id: step.id, name: step.name, uses: step.uses, runs }
}

function planSteps(
    jobId: string,
    steps: RawStep[],
    context: Context,
    env: Record<string, string>,
    stubs: Record<string, StepStub>,
    cancelled: boolean,
    errors: PlanError[]
): { steps: StepPlan[]; stepContexts: Record<string, StepContext>; failed: boolean } {
    const stepContexts: Record<string, StepContext> = {}
    const plans: StepPlan[] = []
    let failed = false
    steps.forEach((step, index) => {
        const stepStatus = planFunctions({
            dependenciesSucceeded: !failed,
            dependenciesFailed: failed,
            cancelled,
        })
        const stepContext: Context = { ...context, steps: stepContexts as unknown as JsonValue }
        let runs = false
        try {
            const stepEnv = evaluateEnv(step.env, stepContext, stepStatus)
            runs = evaluateCondition(step.if, { ...stepContext, env: { ...env, ...stepEnv } }, stepStatus)
        } catch (error) {
            errors.push({ job: jobId, step: step.id ?? `#${index}`, where: 'if', message: String(error) })
        }
        const stub = stubs[step.id ?? ''] ?? stubs[step.name ?? '']
        const outcome: Outcome = runs ? (stub?.outcome ?? 'success') : 'skipped'
        const continueOnError = evaluateTemplate(step['continue-on-error'], stepContext, stepStatus) === 'true'
        const conclusion: Outcome = outcome === 'failure' && continueOnError ? 'success' : outcome
        if (outcome === 'failure' && !continueOnError) {
            failed = true
        }
        if (step.id) {
            stepContexts[step.id] = { outputs: runs ? (stub?.outputs ?? {}) : {}, outcome, conclusion }
        }
        plans.push(toStepPlan(step, index, runs))
    })
    return { steps: plans, stepContexts, failed }
}

export function planWorkflow(workflow: Workflow, scenario: Scenario): WorkflowPlan {
    const errors: PlanError[] = []
    const jobs: Record<string, JobPlan> = {}
    const completed = new Set(scenario.completedBeforeCancel ?? [])
    const baseContext: Context = {
        github: scenario.github,
        vars: scenario.vars ?? {},
        inputs: {},
        secrets: { GITHUB_TOKEN: 'stub-token' },
        matrix: {},
        runner: { os: 'Linux', arch: 'X64', name: 'workflow-plan' },
        strategy: {},
    }
    const workflowEnv = evaluateEnv(
        workflow.env,
        baseContext,
        planFunctions({ dependenciesSucceeded: true, dependenciesFailed: false, cancelled: false })
    )

    for (const jobId of jobOrder(workflow.jobs)) {
        const job = workflow.jobs[jobId]!
        const cancelled = !!scenario.cancelled && !completed.has(jobId)
        const needs = needIds(job)
        const needsContext = Object.fromEntries(
            needs.map((need) => [need, { result: jobs[need]?.result ?? 'success', outputs: jobs[need]?.outputs ?? {} }])
        )
        const needResults = Object.values(needsContext).map((need) => need.result)
        const status = planFunctions({
            dependenciesSucceeded: needResults.every((result) => result === 'success'),
            dependenciesFailed: needResults.some((result) => result === 'failure'),
            cancelled,
        })
        const contextWithoutEnv: Context = {
            ...baseContext,
            needs: needsContext,
            job: { status: 'success' },
        }
        let env: Record<string, string> = { ...workflowEnv }
        try {
            env = { ...env, ...evaluateEnv(job.env, contextWithoutEnv, status) }
        } catch (error) {
            errors.push({ job: jobId, where: 'env', message: String(error) })
        }
        const context: Context = { ...contextWithoutEnv, env }

        let runs = false
        try {
            runs = evaluateCondition(job.if, context, status)
        } catch (error) {
            errors.push({ job: jobId, where: 'if', message: String(error) })
        }

        const allSteps = flattenSteps(job.steps)
        if (!runs) {
            jobs[jobId] = {
                id: jobId,
                result: cancelled ? 'cancelled' : 'skipped',
                outputs: {},
                steps: allSteps.map((step, index) => toStepPlan(step, index, false)),
                matrixCells: undefined,
            }
            continue
        }

        let matrixCells: number | undefined
        try {
            matrixCells = countMatrixCells(job.strategy?.matrix, context, status)
        } catch (error) {
            errors.push({ job: jobId, where: 'matrix', message: String(error) })
        }

        const stepPlan = planSteps(jobId, allSteps, context, env, scenario.steps?.[jobId] ?? {}, cancelled, errors)
        let outputs: Record<string, string> = {}
        try {
            outputs = evaluateEnv(
                job.outputs,
                { ...context, steps: stepPlan.stepContexts as unknown as JsonValue },
                status
            )
        } catch (error) {
            errors.push({ job: jobId, where: 'outputs', message: String(error) })
        }
        for (const [key, value] of Object.entries(outputs)) {
            outputs[key] = value.trim()
        }
        jobs[jobId] = {
            id: jobId,
            result: stepPlan.failed ? 'failure' : 'success',
            outputs: { ...outputs, ...scenario.jobOutputs?.[jobId] },
            steps: stepPlan.steps,
            matrixCells,
        }
    }
    return { jobs, errors }
}

export function formatPlanError(scenarioName: string, error: PlanError): string {
    const site = error.step ? `${error.job}/${error.step}` : error.job
    return `${scenarioName}: ${site} ${error.where}: ${error.message}`
}

export function runningJobs(plan: WorkflowPlan): string[] {
    return Object.values(plan.jobs)
        .filter((job) => job.result === 'success' || job.result === 'failure')
        .map((job) => job.id)
}
