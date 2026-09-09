import { load } from 'js-yaml'

import type { Context, JsonValue } from './expressions.ts'
import { type RawStep, type Scenario, type StepStub, type Workflow, flattenSteps } from './plan.ts'

export const REPOSITORY = 'PostHog/posthog'
export const FORK_REPOSITORY = 'octocat/posthog'
export const DEFAULT_BRANCH = 'master'

const HEAD_SHA = 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678'
const BASE_SHA = 'f9e8d7c6b5a4938271605f4e3d2c1b0a98765432'

export type PullRequestAction =
    | 'opened'
    | 'synchronize'
    | 'reopened'
    | 'ready_for_review'
    | 'labeled'
    | 'unlabeled'
    | 'closed'

export interface PullRequestOptions {
    draft?: boolean
    labels?: readonly string[]
    fork?: boolean
    headRef?: string
    baseRef?: string
    action?: PullRequestAction
    /** The label the `labeled` / `unlabeled` event carries. */
    label?: string
    actor?: string
    number?: number
}

function repositoryPayload(fullName: string): JsonValue {
    const [owner, name] = fullName.split('/')
    return {
        full_name: fullName,
        name: name ?? fullName,
        owner: { login: owner ?? '' },
        default_branch: DEFAULT_BRANCH,
    }
}

function baseContext(eventName: string, actor: string): Context {
    return {
        event_name: eventName,
        repository: REPOSITORY,
        repository_owner: 'PostHog',
        actor,
        triggering_actor: actor,
        run_id: '1000',
        run_number: '1',
        run_attempt: '1',
        workflow: 'workflow',
        job: 'job',
        server_url: 'https://github.com',
        api_url: 'https://api.github.com',
        token: 'stub-token',
        sha: HEAD_SHA,
    }
}

export function pullRequest(options: PullRequestOptions = {}): Context {
    const {
        draft = false,
        labels = [],
        fork = false,
        headRef = 'feat/example',
        baseRef = DEFAULT_BRANCH,
        action = 'synchronize',
        label,
        actor = 'octocat',
        number = 1,
    } = options
    const headRepository = fork ? FORK_REPOSITORY : REPOSITORY
    const event: Record<string, JsonValue> = {
        action,
        number,
        repository: repositoryPayload(REPOSITORY),
        pull_request: {
            number,
            draft,
            state: 'open',
            title: 'Example change',
            labels: labels.map((name) => ({ name })),
            user: { login: actor },
            head: { ref: headRef, sha: HEAD_SHA, repo: { ...(repositoryPayload(headRepository) as object), fork } },
            base: { ref: baseRef, sha: BASE_SHA, repo: repositoryPayload(REPOSITORY) },
        },
    }
    if (label !== undefined) {
        event['label'] = { name: label }
    }
    return {
        ...baseContext('pull_request', actor),
        ref: `refs/pull/${number}/merge`,
        ref_name: `${number}/merge`,
        head_ref: headRef,
        base_ref: baseRef,
        event,
    }
}

/** The Trunk merge queue tests a `trunk-merge/**` branch through a draft pull request. */
export function mergeQueue(options: Omit<PullRequestOptions, 'headRef' | 'draft'> = {}): Context {
    return pullRequest({ ...options, draft: true, headRef: 'trunk-merge/abc123' })
}

export function push(branch = DEFAULT_BRANCH, actor = 'octocat'): Context {
    return {
        ...baseContext('push', actor),
        ref: `refs/heads/${branch}`,
        ref_name: branch,
        head_ref: '',
        base_ref: '',
        event: {
            ref: `refs/heads/${branch}`,
            before: BASE_SHA,
            after: HEAD_SHA,
            repository: repositoryPayload(REPOSITORY),
            head_commit: { id: HEAD_SHA, message: 'feat: example', timestamp: '2026-01-01T00:00:00Z' },
        },
    }
}

export function schedule(cron = '0 * * * *'): Context {
    return {
        ...baseContext('schedule', 'github-actions[bot]'),
        ref: `refs/heads/${DEFAULT_BRANCH}`,
        ref_name: DEFAULT_BRANCH,
        head_ref: '',
        base_ref: '',
        event: { schedule: cron, repository: repositoryPayload(REPOSITORY) },
    }
}

export function workflowDispatch(inputs: Record<string, JsonValue> = {}, branch = DEFAULT_BRANCH): Context {
    return {
        ...baseContext('workflow_dispatch', 'octocat'),
        ref: `refs/heads/${branch}`,
        ref_name: branch,
        head_ref: '',
        base_ref: '',
        event: { inputs, ref: `refs/heads/${branch}`, repository: repositoryPayload(REPOSITORY) },
    }
}

/** What the vendored paths-filter action emits for a run where the given filters matched or not. */
export function pathsFilter(changed: Record<string, boolean>): StepStub {
    const outputs: Record<string, string> = {
        changes: JSON.stringify(Object.keys(changed).filter((name) => changed[name])),
    }
    for (const [name, matched] of Object.entries(changed)) {
        outputs[name] = matched ? 'true' : 'false'
        outputs[`${name}_files`] = matched ? `example/${name}.txt` : ''
    }
    return { outputs }
}

function filterNames(step: RawStep): string[] {
    const filters = step.with?.['filters']
    if (typeof filters === 'string') {
        const parsed = load(filters)
        return typeof parsed === 'object' && parsed !== null ? Object.keys(parsed) : []
    }
    if (typeof filters === 'object' && filters !== null) {
        return Object.keys(filters)
    }
    return []
}

function isPathsFilterStep(step: RawStep): step is RawStep & { id: string } {
    return typeof step.id === 'string' && typeof step.uses === 'string' && step.uses.includes('paths-filter')
}

/** Stubs every paths-filter step in the workflow as if every one of its filters matched. */
export function allFiltersChanged(workflow: Workflow): Record<string, Record<string, StepStub>> {
    const stubs: Record<string, Record<string, StepStub>> = {}
    for (const [jobId, job] of Object.entries(workflow.jobs)) {
        for (const step of flattenSteps(job.steps)) {
            if (!isPathsFilterStep(step)) {
                continue
            }
            const changed = Object.fromEntries(filterNames(step).map((name) => [name, true]))
            stubs[jobId] = { ...stubs[jobId], [step.id]: pathsFilter(changed) }
        }
    }
    return stubs
}

export function defaultScenarios(workflow: Workflow): Scenario[] {
    const steps = allFiltersChanged(workflow)
    return [
        { name: 'draft PR', github: pullRequest({ draft: true }), steps },
        { name: 'ready PR', github: pullRequest(), steps },
        { name: 'fork PR', github: pullRequest({ fork: true }), steps },
        { name: 'merge queue', github: mergeQueue(), steps },
        { name: 'master push', github: push(), steps },
        { name: 'schedule', github: schedule(), steps },
        { name: 'dispatch', github: workflowDispatch(), steps },
        { name: 'ready PR, cancelled', github: pullRequest(), steps, cancelled: true },
    ]
}
