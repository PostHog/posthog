import { load } from 'js-yaml'
import { readFileSync } from 'node:fs'

import {
    type Context,
    type ExpressionFunction,
    type JsonValue,
    containsExpression,
    evaluateCondition,
    evaluateTemplate,
    evaluateValue,
    statusFunctions,
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
    env?: Record<string, string>
    inputs?: Record<string, JsonValue>
    secrets?: Record<string, string>
    /** Stubbed step results by job id, then step id (or name). Steps the plan skips lose their stubbed outputs. */
    steps?: Record<string, Record<string, StepStub>>
    /** Overrides a job's evaluated outputs, for reusable-workflow calls and script-driven outputs. */
    jobOutputs?: Record<string, Record<string, string>>
    matrix?: Record<string, Record<string, JsonValue>>
    failJobs?: readonly string[]
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
    reusable: boolean
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

export function triggerNames(workflow: Workflow): string[] {
    const on = workflow.on
    if (typeof on === 'string') {
        return [on]
    }
    if (Array.isArray(on)) {
        return on.map(String)
    }
    if (typeof on === 'object' && on !== null) {
        return Object.keys(on)
    }
    return []
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
    functions: Map<string, ExpressionFunction>
): Record<string, string> {
    const env: Record<string, string> = {}
    for (const [key, value] of Object.entries(raw ?? {})) {
        env[key] = evaluateTemplate(value, context, functions)
    }
    return env
}

function resolveMatrixValue(raw: unknown, context: Context, functions: Map<string, ExpressionFunction>): unknown {
    return containsExpression(raw) ? evaluateValue(raw, context, functions) : raw
}

export function countMatrixCells(
    rawMatrix: unknown,
    context: Context,
    functions: Map<string, ExpressionFunction>
): number | undefined {
    if (rawMatrix === undefined || rawMatrix === null) {
        return undefined
    }
    const matrix = resolveMatrixValue(rawMatrix, context, functions)
    if (Array.isArray(matrix)) {
        return matrix.length
    }
    if (typeof matrix !== 'object' || matrix === null) {
        return undefined
    }
    const entries = matrix as Record<string, unknown>
    const include = resolveMatrixValue(entries['include'], context, functions)
    const includeCount = Array.isArray(include) ? include.length : 0
    const axes = Object.entries(entries)
        .filter(([key]) => key !== 'include' && key !== 'exclude')
        .map(([, value]) => resolveMatrixValue(value, context, functions))
        .map((value) => (Array.isArray(value) ? value.length : 1))
    if (axes.length === 0) {
        return includeCount
    }
    return axes.reduce((product, size) => product * size, 1) + includeCount
}

function planSteps(
    jobId: string,
    steps: RawStep[],
    context: Context,
    env: Record<string, string>,
    scenario: Scenario,
    errors: PlanError[]
): { steps: StepPlan[]; stepContexts: Record<string, StepContext>; failed: boolean } {
    const stepContexts: Record<string, StepContext> = {}
    const plans: StepPlan[] = []
    let failed = false
    steps.forEach((step, index) => {
        const stepStatus = statusFunctions({
            dependenciesSucceeded: !failed,
            dependenciesFailed: failed,
            cancelled: !!scenario.cancelled,
        })
        const stepContext: Context = { ...context, steps: stepContexts as unknown as JsonValue }
        let runs = false
        try {
            const stepEnv = evaluateEnv(step.env, stepContext, stepStatus)
            runs = evaluateCondition(step.if, { ...stepContext, env: { ...env, ...stepEnv } }, stepStatus)
        } catch (error) {
            errors.push({ job: jobId, step: step.id ?? `#${index}`, where: 'if', message: String(error) })
        }
        const jobStubs = scenario.steps?.[jobId]
        const stub = (step.id ? jobStubs?.[step.id] : undefined) ?? (step.name ? jobStubs?.[step.name] : undefined)
        const outcome: Outcome = runs ? (stub?.outcome ?? 'success') : 'skipped'
        const continueOnError = evaluateTemplate(step['continue-on-error'], stepContext, stepStatus) === 'true'
        const conclusion: Outcome = outcome === 'failure' && continueOnError ? 'success' : outcome
        if (outcome === 'failure' && !continueOnError) {
            failed = true
        }
        if (step.id) {
            stepContexts[step.id] = { outputs: runs ? (stub?.outputs ?? {}) : {}, outcome, conclusion }
        }
        plans.push({ index, id: step.id, name: step.name, uses: step.uses, runs })
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
        inputs: scenario.inputs ?? {},
        secrets: { GITHUB_TOKEN: 'stub-token', ...scenario.secrets },
        runner: { os: 'Linux', arch: 'X64', name: 'workflow-plan' },
        strategy: {},
    }
    const workflowEnv = evaluateEnv(
        workflow.env,
        baseContext,
        statusFunctions({ dependenciesSucceeded: true, dependenciesFailed: false, cancelled: false })
    )

    for (const jobId of jobOrder(workflow.jobs)) {
        const job = workflow.jobs[jobId]!
        const cancelled = !!scenario.cancelled && !completed.has(jobId)
        const needs = needIds(job)
        const needResults = needs.map((need) => jobs[need]?.result ?? 'success')
        const status = statusFunctions({
            dependenciesSucceeded: needResults.every((result) => result === 'success'),
            dependenciesFailed: needResults.some((result) => result === 'failure'),
            cancelled,
        })
        const needsContext: Record<string, JsonValue> = Object.fromEntries(
            needs.map((need) => [need, { result: jobs[need]?.result ?? 'success', outputs: jobs[need]?.outputs ?? {} }])
        )
        const contextWithoutEnv: Context = {
            ...baseContext,
            needs: needsContext,
            matrix: scenario.matrix?.[jobId] ?? {},
            job: { status: 'success' },
        }
        let env: Record<string, string> = { ...workflowEnv }
        try {
            env = { ...env, ...evaluateEnv(job.env, contextWithoutEnv, status), ...scenario.env }
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

        const reusable = typeof job.uses === 'string'
        const allSteps = flattenSteps(job.steps)
        if (!runs) {
            jobs[jobId] = {
                id: jobId,
                result: cancelled ? 'cancelled' : 'skipped',
                outputs: {},
                steps: allSteps.map((step, index) => ({
                    index,
                    id: step.id,
                    name: step.name,
                    uses: step.uses,
                    runs: false,
                })),
                matrixCells: undefined,
                reusable,
            }
            continue
        }

        let matrixCells: number | undefined
        try {
            matrixCells = countMatrixCells(job.strategy?.matrix, context, status)
        } catch (error) {
            errors.push({ job: jobId, where: 'matrix', message: String(error) })
        }

        const stepPlan = planSteps(jobId, allSteps, context, env, { ...scenario, cancelled }, errors)
        const failed = stepPlan.failed || (scenario.failJobs ?? []).includes(jobId)
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
            result: failed ? 'failure' : 'success',
            outputs: { ...outputs, ...scenario.jobOutputs?.[jobId] },
            steps: stepPlan.steps,
            matrixCells,
            reusable,
        }
    }
    return { jobs, errors }
}

export function runningJobs(plan: WorkflowPlan): string[] {
    return Object.values(plan.jobs)
        .filter((job) => job.result === 'success' || job.result === 'failure')
        .map((job) => job.id)
}
