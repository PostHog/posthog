/**
 * CLI local execution mode (spec §4.8): wires the code-execution verbs
 * (`types` / `run` / `apply`) to run in-process on the user's machine. Scripts
 * execute against the user's own key on their own machine, so the sandbox is a
 * prompt-injection mitigation rather than a tenant boundary — `trustedLocal`
 * is set here and nowhere else. Plans persist as files under the PostHog home
 * directory because every CLI invocation is a separate process.
 */

import { promises as fs } from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import classifierTableJson from '@/generated/code-exec/classifier-table.json'
import { type ClassifierTable, FilePlanStore } from '@/lib/code-exec'
import { AnalyticsEvent } from '@/lib/posthog/analytics'
import { LocalVmExecutor } from '@/tools/code-exec/executor'
import {
    type ApplyOutcome,
    type CodeExecutionDiscovery,
    type CodeExecutionRuntime,
    createCodeExecutionDiscovery,
    createCodeExecutionRuntime,
    type RunOutcome,
} from '@/tools/code-exec/runtime'
import type { Context } from '@/tools/types'

import { takeFlag, takeOption } from './args'

const RUN_USAGE = "Usage: posthog-cli api run [--yes] [--file <path> | -] ['<typescript source>']"

/** Mirror of the Rust CLI's home-dir convention (`cli/src/utils/homedir.rs`). */
export function resolvePosthogHome(): string {
    return process.env.POSTHOG_HOME ?? path.join(os.homedir(), '.posthog')
}

export function cliPlanDirectory(): string {
    return path.join(resolvePosthogHome(), 'code-exec', 'plans')
}

/**
 * Resolve the key's real scopes for scope-annotated `types` output. Fail soft
 * to `'*'` (which short-circuits every scope check): resolution can fail on
 * OAuth-style tokens, and a missing annotation is better than a wall of
 * misleading "missing on this token" — real gaps surface at API-call time.
 */
export async function resolveCliSessionScopes(context: Context): Promise<string[]> {
    try {
        return (await context.stateManager.getApiKey()).scopes
    } catch {
        return ['*']
    }
}

export interface CliCodeExecution {
    discovery: CodeExecutionDiscovery
    runtime: CodeExecutionRuntime
}

export function buildCliCodeExecution(context: Context, sessionScopes: string[]): CliCodeExecution {
    return {
        discovery: createCodeExecutionDiscovery({ sessionScopes }),
        runtime: createCodeExecutionRuntime({
            realFetch: (input, init) => context.api.fetchRaw(input, init),
            getSub: () => context.getDistinctId(),
            // Session project/org, exactly as the tool handlers resolve them —
            // sandboxed scripts must not fall back to the `@me` current team.
            getProjectId: () => context.stateManager.getProjectId(),
            getOrgId: () => context.stateManager.getOrgID(),
            planStore: new FilePlanStore({ directory: cliPlanDirectory() }),
            // The one place `trustedLocal` may be set (spec §4.8) — this code
            // path only runs on the user's own machine with their own key.
            executor: new LocalVmExecutor({ trustedLocal: true }),
            // The generated artifact matches `ClassifierTable` field-for-field, but
            // JSON import inference widens the `idFields[].type` literals to string.
            classifierTable: classifierTableJson as unknown as ClassifierTable,
            // No compileGate: the distributed bundle ships without `typescript`
            // beside it, so `run` uses the contract lints and its output notes
            // that the typecheck was skipped (spec §4.8).
        }),
    }
}

export type RunSourceSpec = { kind: 'file'; path: string } | { kind: 'stdin' } | { kind: 'inline'; source: string }

export interface RunInvocation {
    yes: boolean
    source: RunSourceSpec
}

/** Parse `run` arguments: `--yes`, then `--file <path>` | `-` (stdin) | inline source words. */
export function parseRunArgs(args: string[], opts: { stdinIsTty: boolean }): RunInvocation {
    const yes = takeFlag(args, '--yes')
    const file = takeOption(args, '--file')
    if (file !== undefined) {
        if (args.length > 0) {
            throw new Error(`run takes either --file <path> or inline source, not both.\n${RUN_USAGE}`)
        }
        return { yes, source: { kind: 'file', path: file } }
    }
    if (args.length === 1 && args[0] === '-') {
        return { yes, source: { kind: 'stdin' } }
    }
    if (args.length === 0) {
        // Bare `run` with piped input reads the script from stdin, like `run -`.
        if (!opts.stdinIsTty) {
            return { yes, source: { kind: 'stdin' } }
        }
        throw new Error(RUN_USAGE)
    }
    return { yes, source: { kind: 'inline', source: args.join(' ') } }
}

export async function resolveRunSource(spec: RunSourceSpec): Promise<string> {
    switch (spec.kind) {
        case 'file':
            return fs.readFile(spec.path, 'utf8')
        case 'stdin':
            return readStdin()
        case 'inline':
            return spec.source
    }
}

async function readStdin(): Promise<string> {
    const chunks: Buffer[] = []
    for await (const chunk of process.stdin) {
        chunks.push(chunk as Buffer)
    }
    return Buffer.concat(chunks).toString('utf8')
}

export interface CliCodeExecDeps {
    context: Context
    print: (result: unknown) => void
}

/**
 * Verb-labelled `$mcp_tool_call` parity with the hosted exec verbs (spec §4.6
 * Phase 0): the `$mcp_mode: 'cli'` / `$mcp_consumer: 'posthog-cli'` stamps
 * ride on `context.trackEvent`, this adds the same `$mcp_exec_*` dimensions
 * `tool-executor.ts` stamps so CLI adoption lands in the same dashboards.
 */
function trackVerbEvent(
    context: Context,
    verb: 'types' | 'run' | 'apply',
    startedAt: number,
    isError: boolean,
    extra: Record<string, unknown> = {}
): void {
    void context.trackEvent(AnalyticsEvent.MCP_TOOL_CALL, {
        tool_name: 'exec',
        $mcp_tool_name: 'exec',
        $mcp_duration_ms: Date.now() - startedAt,
        $mcp_is_error: isError,
        $mcp_exec_verb: verb,
        ...extra,
    })
}

function errorProperties(error: unknown): Record<string, unknown> {
    return { error_message: error instanceof Error ? error.message : String(error) }
}

export async function runCliTypes(
    deps: CliCodeExecDeps,
    discovery: CodeExecutionDiscovery,
    query: string
): Promise<void> {
    const startedAt = Date.now()
    let result: string
    try {
        result = await discovery.types(query)
    } catch (error) {
        trackVerbEvent(deps.context, 'types', startedAt, true, errorProperties(error))
        throw error
    }
    deps.print(result)
    trackVerbEvent(deps.context, 'types', startedAt, false)
}

export async function runCliRun(
    deps: CliCodeExecDeps,
    runtime: CodeExecutionRuntime,
    invocation: { source: string; yes: boolean }
): Promise<void> {
    const startedAt = Date.now()
    let outcome: RunOutcome
    try {
        outcome = await runtime.run(invocation.source)
    } catch (error) {
        trackVerbEvent(deps.context, 'run', startedAt, true, errorProperties(error))
        throw error
    }
    deps.print(outcome.output)
    trackVerbEvent(deps.context, 'run', startedAt, false, {
        $mcp_exec_run_status: outcome.meta.status,
        $mcp_exec_fast_path: outcome.meta.fastPath,
        ...(outcome.meta.planMutations !== undefined ? { $mcp_exec_plan_mutations: outcome.meta.planMutations } : {}),
    })
    // `--yes` (spec §3.6.7 / §4.8, scripted/CI use): the plan was already
    // printed above; apply it in the same invocation and print the receipt.
    if (invocation.yes && outcome.meta.planId !== undefined) {
        await runCliApply(deps, runtime, outcome.meta.planId)
    }
}

export async function runCliApply(deps: CliCodeExecDeps, runtime: CodeExecutionRuntime, planId: string): Promise<void> {
    const startedAt = Date.now()
    let outcome: ApplyOutcome
    try {
        outcome = await runtime.apply(planId)
    } catch (error) {
        trackVerbEvent(deps.context, 'apply', startedAt, true, errorProperties(error))
        throw error
    }
    deps.print(outcome.output)
    trackVerbEvent(deps.context, 'apply', startedAt, false, { $mcp_exec_run_status: outcome.meta.status })
}
