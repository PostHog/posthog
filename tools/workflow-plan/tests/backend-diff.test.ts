import { type SpawnSyncReturns, execFileSync, spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

import { type Context, type JsonValue, evaluateCondition, evaluateTemplate, planFunctions } from '../src/expressions.ts'
import { type RawStep, type Workflow, loadWorkflow, planWorkflow } from '../src/plan.ts'
import { REPO_ROOT, allFiltersChanged, mergeQueue, pullRequest } from '../src/scenarios.ts'

const WORKFLOWS = ['.github/workflows/ci-backend.yml', '.depot/workflows/ci-backend.yml']
const functions = planFunctions({ dependenciesSucceeded: true, dependenciesFailed: false, cancelled: false })
const lowerFile = 'products/engineering_analytics/backend/lower.py'
const layerFiles = [
    'products/engineering_analytics/backend/first.py',
    'products/engineering_analytics/backend/second.py',
]
const unrelatedFile = 'products/experiments/backend/unrelated.py'

function createGraph(): {
    cwd: string
    env: NodeJS.ProcessEnv
    git: (...args: string[]) => string
    lower: string
    integration: string
    head: string
    merge: string
    queueMerge: string
} {
    const cwd = mkdtempSync(path.join(os.tmpdir(), 'backend-pr-diff-'))
    const env = {
        ...process.env,
        GIT_CONFIG_GLOBAL: os.devNull,
        GIT_CONFIG_NOSYSTEM: '1',
        GIT_AUTHOR_NAME: 'Test',
        GIT_AUTHOR_EMAIL: 'test@example.com',
        GIT_COMMITTER_NAME: 'Test',
        GIT_COMMITTER_EMAIL: 'test@example.com',
        GIT_AUTHOR_DATE: '2026-01-01T00:00:00Z',
        GIT_COMMITTER_DATE: '2026-01-01T00:00:00Z',
    }
    const git = (...args: string[]): string =>
        execFileSync('git', args, { cwd, env, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }).trim()
    const commit = (file: string): string => {
        mkdirSync(path.dirname(path.join(cwd, file)), { recursive: true })
        writeFileSync(path.join(cwd, file), 'value = 1\n')
        git('add', file)
        git('commit', '-m', 'test')
        return git('rev-parse', 'HEAD')
    }
    git('init', '--initial-branch=master')
    commit('README')
    git('checkout', '-b', 'lower')
    const lower = commit(lowerFile)
    git('update-ref', 'refs/remotes/origin/lower', lower)
    git('checkout', '-b', 'middle')
    commit(layerFiles[0]!)
    const head = commit(layerFiles[1]!)
    git('checkout', 'master')
    const trunk = commit(unrelatedFile)
    git('update-ref', 'refs/remotes/origin/master', trunk)
    git('merge', '--no-ff', 'lower', '-m', 'lower integration')
    const integration = git('rev-parse', 'HEAD')
    git('merge', '--no-ff', 'middle', '-m', 'middle integration')
    const merge = git('rev-parse', 'HEAD')
    const queueMerge = git('commit-tree', `${merge}^{tree}`, '-p', trunk, '-p', merge, '-m', 'queue integration')
    return { cwd, env, git, lower, integration, head, merge, queueMerge }
}

function prContext(sha: string, head: string, base: string, queued = false): Context {
    const github = queued ? mergeQueue() : pullRequest()
    const event = github.event as Record<string, JsonValue>
    const pr = event.pull_request as Record<string, JsonValue>
    github.sha = sha
    github.base_ref = base
    pr.head = { ...(pr.head as object), sha: head }
    pr.base = { ...(pr.base as object), ref: base }
    return { github, needs: { changes: { outputs: { backend: 'true', legacy: 'false', schema: 'false' } } } }
}

function step(wf: Workflow, name: string): RawStep {
    const found = wf.jobs['turbo-discover']!.steps!.find((candidate) => candidate.name === name)
    if (!found) {
        throw new Error(`Missing workflow step: ${name}`)
    }
    return found
}

function envValues(env: RawStep['env'], context: Context): Record<string, string> {
    return Object.fromEntries(
        Object.entries(env ?? {}).map(([key, value]) => [key, evaluateTemplate(value, context, functions)])
    )
}

function stepEnv(wf: Workflow, target: RawStep, input: Context): Record<string, string> {
    const context = { steps: {}, vars: {}, needs: {}, ...input }
    const env = envValues(wf.jobs['turbo-discover']!.env, context)
    return { ...env, ...envValues(target.env, { ...context, env }) }
}

function selectorArgs(target: RawStep, cwd: string, env: NodeJS.ProcessEnv): string[] {
    const bin = path.join(cwd, 'bin')
    const argv = path.join(cwd, 'argv.txt')
    mkdirSync(bin)
    writeFileSync(
        path.join(bin, 'uv'),
        '#!/bin/sh\nif [ "$2" = tools/snob_backend_test_selection_shadow.py ]; then\n  printf "%s\\n" "$@" > "$ARGV_OUTPUT"\nfi\nprintf "{}\\n"\n',
        { mode: 0o755 }
    )
    // Keep artifact paths isolated while executing the workflow's Bash and Git commands.
    const script = target
        .run!.replaceAll('/tmp/selection.json', path.join(cwd, 'selection.json'))
        .replaceAll('/tmp/verdict', path.join(cwd, 'verdict'))
    const result = spawnSync('bash', ['-c', script], {
        cwd,
        env: { ...env, PATH: `${bin}:${env.PATH}`, ARGV_OUTPUT: argv, GITHUB_STEP_SUMMARY: path.join(cwd, 'summary') },
        encoding: 'utf8',
    })
    expect(result).toMatchObject({ status: 0 })
    return readFileSync(argv, 'utf8').trim().split('\n')
}

function requiredGate(wf: Workflow, cwd: string, context: Context): SpawnSyncReturns<string> {
    const body = wf.jobs.django_tests!.steps!.find((candidate) => candidate.name === 'Check dependency results')!.run!
    const bin = path.join(cwd, 'bin')
    mkdirSync(bin)
    // The Python process renders JUnit details; Bash owns the required-check verdict.
    writeFileSync(path.join(bin, 'python3'), '#!/bin/sh\nexit 0\n', { mode: 0o755 })
    return spawnSync('bash', ['-c', evaluateTemplate(body, context, functions)], {
        cwd,
        env: { ...process.env, PATH: `${bin}:${process.env.PATH}` },
        encoding: 'utf8',
    })
}

describe('Backend CI comparison boundaries', () => {
    it.each(WORKFLOWS)('%s selects a stack layer without counting newer trunk files', (file) => {
        const repo = createGraph()
        try {
            const wf = loadWorkflow(path.join(REPO_ROOT, file))
            const context = prContext(repo.merge, repo.head, 'lower')
            const discovery = stepEnv(wf, step(wf, 'Discover products to test'), context)
            const selected = repo.git(
                'diff',
                '--name-only',
                `${discovery.TURBO_SCM_BASE}...${discovery.TURBO_SCM_HEAD}`
            )
            expect(selected.split('\n')).toEqual(layerFiles)
            expect(repo.git('diff', '--name-only', 'origin/lower...HEAD').split('\n')).toEqual([
                ...layerFiles,
                unrelatedFile,
            ])

            const verify = step(wf, 'Verify PR merge for test selection')
            expect(evaluateCondition(verify.if, context, functions)).toBe(true)
            const result = spawnSync('bash', ['-c', verify.run!], {
                cwd: repo.cwd,
                env: { ...repo.env, ...stepEnv(wf, verify, context), GITHUB_SHA: repo.merge },
                encoding: 'utf8',
            })
            expect({ status: result.status, stderr: result.stderr }).toEqual({ status: 0, stderr: '' })

            const selector = step(wf, 'Run the backend test selector')
            const args = selectorArgs(selector, repo.cwd, { ...repo.env, ...stepEnv(wf, selector, context) })
            expect(args[args.indexOf('--base-ref') + 1]).toBe(discovery.TURBO_SCM_BASE)

            const ordinary = prContext(repo.integration, repo.lower, 'master')
            const ordinaryEnv = stepEnv(wf, step(wf, 'Discover products to test'), ordinary)
            expect(
                repo.git('diff', '--name-only', `${ordinaryEnv.TURBO_SCM_BASE}...${ordinaryEnv.TURBO_SCM_HEAD}`)
            ).toBe(lowerFile)
            repo.git('checkout', '--detach', repo.integration)
            const ordinaryCheck = spawnSync('bash', ['-c', verify.run!], {
                cwd: repo.cwd,
                env: { ...repo.env, ...stepEnv(wf, verify, ordinary), GITHUB_SHA: repo.integration },
                encoding: 'utf8',
            })
            expect({ status: ordinaryCheck.status, stderr: ordinaryCheck.stderr }).toEqual({ status: 0, stderr: '' })
        } finally {
            rmSync(repo.cwd, { recursive: true, force: true })
        }
    })

    it.each(WORKFLOWS)('%s uses the pinned queue base and disables the PR selector', (file) => {
        const repo = createGraph()
        try {
            const wf = loadWorkflow(path.join(REPO_ROOT, file))
            const context = prContext(repo.queueMerge, repo.merge, 'master', true)
            const discovery = stepEnv(wf, step(wf, 'Discover products to test'), context)
            expect(discovery.TURBO_SCM_BASE).toBe(`${repo.queueMerge}^1`)
            expect(discovery.SELECTION_APPLIES).toBe('false')
            expect(discovery.LEGACY_CHANGED).toBe('false')
            expect(
                evaluateCondition(
                    step(wf, 'Run the backend test selector').if,
                    { ...context, env: discovery, vars: {} },
                    functions
                )
            ).toBe(false)

            const verify = step(wf, 'Verify PR merge for test selection')
            expect(evaluateCondition(verify.if, context, functions)).toBe(true)
            repo.git('checkout', '--detach', repo.queueMerge)
            const result = spawnSync('bash', ['-c', verify.run!], {
                cwd: repo.cwd,
                env: { ...repo.env, ...stepEnv(wf, verify, context), GITHUB_SHA: repo.queueMerge },
                encoding: 'utf8',
            })
            expect({ status: result.status, stderr: result.stderr }).toEqual({ status: 0, stderr: '' })
            expect(
                repo.git('diff', '--name-only', `${discovery.TURBO_SCM_BASE}...${discovery.TURBO_SCM_HEAD}`).split('\n')
            ).toEqual([layerFiles[0], lowerFile, layerFiles[1]])
        } finally {
            rmSync(repo.cwd, { recursive: true, force: true })
        }
    })

    it.each(['wrong-head', 'wrong-checkout', 'shallow'] as const)(
        'rejects %s rather than selecting from an invalid merge',
        (failure) => {
            const repo = createGraph()
            try {
                const wf = loadWorkflow(path.join(REPO_ROOT, WORKFLOWS[0]!))
                const context = prContext(repo.merge, failure === 'wrong-head' ? repo.lower : repo.head, 'lower')
                if (failure === 'wrong-checkout') {
                    repo.git('checkout', '--detach', repo.head)
                } else if (failure === 'shallow') {
                    writeFileSync(path.join(repo.cwd, '.git/shallow'), `${repo.merge}\n`)
                }
                const verify = step(wf, 'Verify PR merge for test selection')
                const result = spawnSync('bash', ['-c', verify.run!], {
                    cwd: repo.cwd,
                    env: { ...repo.env, ...stepEnv(wf, verify, context), GITHUB_SHA: repo.merge },
                    encoding: 'utf8',
                })
                expect(result.status).not.toBe(0)
                const plan = planWorkflow(wf, {
                    name: failure,
                    github: context.github as Context,
                    steps: { ...allFiltersChanged(wf), 'turbo-discover': { 'verify-merge': { outcome: 'failure' } } },
                })
                expect(plan.errors).toEqual([])
                expect(plan.jobs['turbo-discover']!.result).toBe('failure')
                expect(plan.jobs.django_tests!.steps.some((candidate) => candidate.runs)).toBe(true)
                expect(plan.jobs['turbo-tests']!.result).toBe('skipped')
                const gate = wf.jobs.django_tests!
                const needs = Object.fromEntries(
                    (gate.needs as string[]).map((id) => [
                        id,
                        {
                            result: plan.jobs[id]!.result,
                            outputs: plan.jobs[id]!.outputs,
                        },
                    ])
                )
                const verdict = requiredGate(wf, repo.cwd, { needs })
                expect(verdict.status).toBe(1)
                expect(verdict.stdout).toContain('Turbo discover did not succeed')
            } finally {
                rmSync(repo.cwd, { recursive: true, force: true })
            }
        }
    )

    it.each([
        { name: 'ordinary PR', queued: false },
        { name: 'queue PR', queued: true },
    ])('regenerates a missing verdict selection for $name', ({ queued }) => {
        const repo = createGraph()
        try {
            const wf = loadWorkflow(path.join(REPO_ROOT, WORKFLOWS[0]!))
            const sha = queued ? repo.queueMerge : repo.merge
            const context = prContext(sha, queued ? repo.merge : repo.head, queued ? 'master' : 'lower', queued)
            const target = wf.jobs['test-selection-verdict']!.steps!.find(
                (candidate) => candidate.name === 'Run test selection and verdict'
            )!
            repo.git('checkout', '--detach', sha)
            const args = selectorArgs(target, repo.cwd, {
                ...repo.env,
                ...envValues(target.env, context),
                GITHUB_SHA: sha,
            })
            const base = args[args.indexOf('--base-ref') + 1]!
            expect(repo.git('diff', '--name-only', `${base}...HEAD`).split('\n')).toEqual(
                queued ? [layerFiles[0], lowerFile, layerFiles[1]] : layerFiles
            )
        } finally {
            rmSync(repo.cwd, { recursive: true, force: true })
        }
    })
})
