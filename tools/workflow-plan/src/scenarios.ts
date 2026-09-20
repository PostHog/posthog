import { load } from 'js-yaml'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import type { Context, JsonValue } from './expressions.ts'
import { type RawStep, type Scenario, type StepStub, type Workflow, flattenSteps } from './plan.ts'

export const REPOSITORY = 'PostHog/posthog'
export const FORK_REPOSITORY = 'octocat/posthog'
export const DEFAULT_BRANCH = 'master'

const FAKE_HEAD_SHA = 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678'
const FAKE_BASE_SHA = 'f9e8d7c6b5a4938271605f4e3d2c1b0a98765432'

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
    action?: PullRequestAction
    /** The label the `labeled` / `unlabeled` event carries. */
    label?: string
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
        sha: FAKE_HEAD_SHA,
    }
}

export function pullRequest(options: PullRequestOptions = {}): Context {
    const {
        draft = false,
        labels = [],
        fork = false,
        headRef = 'feat/example',
        action = 'synchronize',
        label,
    } = options
    const actor = 'octocat'
    const number = 1
    const headRepository = fork ? FORK_REPOSITORY : REPOSITORY
    const event: Record<string, JsonValue> = {
        action,
        number,
        repository: repositoryPayload(REPOSITORY),
        pull_request: {
            number,
            draft,
            state: action === 'closed' ? 'closed' : 'open',
            title: 'Example change',
            labels: labels.map((name) => ({ name })),
            user: { login: actor },
            head: {
                ref: headRef,
                sha: FAKE_HEAD_SHA,
                repo: { ...(repositoryPayload(headRepository) as object), fork },
            },
            base: { ref: DEFAULT_BRANCH, sha: FAKE_BASE_SHA, repo: repositoryPayload(REPOSITORY) },
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
        base_ref: DEFAULT_BRANCH,
        event,
    }
}

/** The Trunk merge queue tests a `trunk-merge/**` branch through a draft pull request. */
export function mergeQueue(options: Omit<PullRequestOptions, 'headRef' | 'draft'> = {}): Context {
    return pullRequest({ ...options, draft: true, headRef: 'trunk-merge/abc123' })
}

function branchContext(eventName: string, actor: string, branch: string = DEFAULT_BRANCH): Context {
    return {
        ...baseContext(eventName, actor),
        ref: `refs/heads/${branch}`,
        ref_name: branch,
        head_ref: '',
        base_ref: '',
    }
}

export function push(): Context {
    return {
        ...branchContext('push', 'octocat'),
        event: {
            ref: `refs/heads/${DEFAULT_BRANCH}`,
            before: FAKE_BASE_SHA,
            after: FAKE_HEAD_SHA,
            repository: repositoryPayload(REPOSITORY),
            head_commit: { id: FAKE_HEAD_SHA, message: 'feat: example', timestamp: '2026-01-01T00:00:00Z' },
        },
    }
}

export function schedule(): Context {
    return {
        ...branchContext('schedule', 'github-actions[bot]'),
        event: { schedule: '0 * * * *', repository: repositoryPayload(REPOSITORY) },
    }
}

export function workflowDispatch(branch: string = DEFAULT_BRANCH): Context {
    return {
        ...branchContext('workflow_dispatch', 'octocat', branch),
        event: { inputs: {}, ref: `refs/heads/${branch}`, repository: repositoryPayload(REPOSITORY) },
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

export const REPO_ROOT = fileURLToPath(new URL('../../../', import.meta.url))

type ScriptStubs = Pick<Scenario, 'vars' | 'jobOutputs'>

// Values only a script produces at runtime, without which a workflow's gates cannot be planned.
const DEPOT_BACKEND = '.depot/workflows/ci-backend.yml'

export const SCRIPT_STUBS: Record<string, ScriptStubs> = {
    '.github/workflows/build-deltalite.yml': {
        jobOutputs: { 'check-version': { 'deltalite-release-needed': 'true' } },
    },
    '.github/workflows/release.yml': {
        jobOutputs: {
            plan: {
                val: JSON.stringify({ ci: { github: { artifacts_matrix: { include: null }, pr_run_mode: 'upload' } } }),
            },
        },
    },
    // The Depot graph hangs off a hand-off check the planner cannot read; plan it as handed
    // off, which is the only case where its jobs do any work.
    [DEPOT_BACKEND]: {
        jobOutputs: { 'wait-for-handoff': { handed_off: 'true' } },
    },
}

// The router keeps forks, merge queue batches, pushes and the schedule on GitHub Actions,
// so Depot's wait job declines those events; only same-repo pull requests and manual
// dispatches run there.
const NOT_HANDED_OFF: ScriptStubs = { jobOutputs: { 'wait-for-handoff': { handed_off: 'false' } } }

export function defaultScenarios(workflow: Workflow, workflowPath: string): Scenario[] {
    const steps = allFiltersChanged(workflow)
    const key = path.relative(REPO_ROOT, workflowPath).split(path.sep).join('/')
    const common = { steps, ...SCRIPT_STUBS[key] }
    const keptOnGitHub = { ...common, ...(key === DEPOT_BACKEND ? NOT_HANDED_OFF : {}) }
    return [
        { name: 'draft', github: pullRequest({ draft: true }), ...common },
        { name: 'ready', github: pullRequest(), ...common },
        { name: 'fork', github: pullRequest({ fork: true }), ...keptOnGitHub },
        { name: 'queued', github: mergeQueue(), ...keptOnGitHub },
        { name: 'merged', github: push(), ...keptOnGitHub },
        { name: 'scheduled', github: schedule(), ...keptOnGitHub },
        { name: 'dispatched', github: workflowDispatch(), ...common },
    ]
}
