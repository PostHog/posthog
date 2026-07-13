/**
 * The two facades behind the code-execution exec verbs; `exec.ts` only sees
 * their interfaces. They are gated independently (spec §4.4): the discovery
 * half (`types` + the tool→method reverse mapping) needs only the generated
 * index, so it serves every flagged client; the runtime half (`run`/`apply`)
 * wires everything stateful — plan transports, plan store, and (where one can
 * run) the sandbox executor. The executor is optional (spec §4.2): without it
 * the runtime still serves call-shaped scripts through the fast path, and
 * everything else gets a targeted sandbox-unavailable error.
 *
 * Flow (spec §3.6/§4.2): `run` first tries the no-sandbox fast path — a
 * call-shaped script dispatches straight through the matching tool handler
 * (read-only) or stores a degenerate one-call plan (mutating). Everything else
 * compiles, executes in plan mode, and either returns results directly (zero
 * mutations) or a rendered plan + a single-use three-word plan id. `apply`
 * consumes the stored plan, refuses if the active project changed since the
 * plan was minted, and branches on its kind: call plans replay the handler
 * directly (no executor involved); script plans re-run the stored script live
 * with the confirmed plan enforced as a contract.
 */

import { randomUUID } from 'node:crypto'

import {
    buildPlan,
    type ClassifierOperation,
    type ClassifierTable,
    createClassifier,
    createEnforceTransport,
    createPlanTransport,
    createSentinelFactory,
    type FetchLike,
    generatePlanPhrase,
    type MutationOutcome,
    normalizePlanPhrase,
    PLAN_PHRASE_TTL_SECONDS,
    PlanDivergenceError,
    type PlanStore,
    type RecordedMutation,
    renderPlanText,
    renderReceiptText,
    type StoredCallPlan,
    type StoredPlan,
} from '@/lib/code-exec'

import { TOKEN_CHAR_LIMIT } from '../schema-utils'
import type { CompileDiagnostic, CompileGateResult } from './compile-gate'
import {
    createDiscovery,
    type Discovery,
    type DiscoveryIndex,
    type DiscoveryMethod,
    getGeneratedDiscovery,
    getGeneratedDiscoveryIndex,
} from './discovery'
import type { SandboxExecutor } from './executor'
import { matchFastPath } from './fast-path'

/** Wall-clock budget for one script execution (plan or apply pass). */
const DEFAULT_SCRIPT_TIMEOUT_MS = 30_000

const REPLAN_HINT = 'Re-run the script with "run <source>" to get a fresh plan and confirm it again.'

/**
 * Verb-level outcome dimension for `$mcp_exec_run_status` (spec §4.6 Phase 0).
 * Kept a closed set — dashboards slice on these values, so renaming is painful.
 * An expired plan is indistinguishable from a mistyped id at consume time
 * (both read as absent), so expiry reports as `not_found`.
 * `sandbox_unavailable`: the script needed the sandbox on a fast-path-only
 * process (spec §4.2) — the direct demand signal for the hosted substrate.
 */
export type ExecRunStatus = 'compile_error' | 'read_only' | 'plan_issued' | 'failed' | 'sandbox_unavailable'
export type ExecApplyStatus = 'applied' | 'already_applied' | 'not_found' | 'diverged' | 'failed'

export interface RunMetadata {
    /** Whether the script was served by the no-sandbox fast path (spec §4.2). */
    fastPath: boolean
    /** Inner tool a fast-pathed script dispatched (or planned). */
    innerToolName?: string
    status: ExecRunStatus
    /** Mutation count, present exactly when a plan was issued. */
    planMutations?: number
    /**
     * Issued plan id (the three-word phrase), present exactly when a plan was
     * issued. Structured so the CLI's `--yes` can apply in the same invocation
     * without scraping the rendered text (spec §4.8). Never an analytics
     * property — `trackVerb` deliberately does not propagate it.
     */
    planId?: string
}

export interface RunOutcome {
    /** What the exec verb returns to the client — text, or a UI-app payload on the fast path. */
    output: unknown
    /** Structured run metadata for verb-level analytics (spec §4.6 Phase 0). */
    meta: RunMetadata
}

export interface ApplyMetadata {
    status: ExecApplyStatus
}

export interface ApplyOutcome {
    output: string
    /** Structured apply metadata for verb-level analytics (spec §4.6 Phase 0). */
    meta: ApplyMetadata
}

/**
 * The static-artifact half of the code-execution surface (spec §4.4). Backs
 * `types`, the code-first legacy-verb aliases, and the deprecation footers —
 * everything here reads the generated discovery index only, so it stays
 * available on servers where no executor (and hence no `run`/`apply`) exists.
 */
export interface CodeExecutionDiscovery {
    types(input: string): Promise<string>
    /**
     * Reverse discovery mapping (MCP tool name → SDK method id); `null` for
     * tools with no SDK counterpart (e.g. SSE-backed tools).
     */
    methodIdForTool(toolName: string): Promise<string | null>
}

export interface CodeExecutionDiscoveryDeps {
    /** Resolved API key scopes, for scope-annotated discovery. */
    sessionScopes: string[]
    /** Test seam; defaults to the generated artifact. */
    discoveryIndex?: DiscoveryIndex
}

export function createCodeExecutionDiscovery(deps: CodeExecutionDiscoveryDeps): CodeExecutionDiscovery {
    let discovery: Discovery | null = deps.discoveryIndex ? createDiscovery(deps.discoveryIndex) : null
    const getDiscovery = async (): Promise<Discovery> => {
        // The generated-artifact instance is process-cached; only its scope
        // annotations vary per session, and those are applied per `resolve`.
        discovery ??= await getGeneratedDiscovery()
        return discovery
    }
    return {
        async types(input) {
            return (await getDiscovery()).resolve(input, deps.sessionScopes)
        },
        async methodIdForTool(toolName) {
            return (await getDiscovery()).methodIdForTool(toolName)
        },
    }
}

export interface CodeExecutionRuntime {
    run(source: string): Promise<RunOutcome>
    apply(planId: string): Promise<ApplyOutcome>
    /**
     * Whether arbitrary scripts can execute here (a sandbox executor is
     * wired). False on fast-path-only processes (spec §4.2) — `run` still
     * serves call-shaped scripts, everything else gets a targeted error. The
     * code-first surface keys off this so it can never activate where the
     * legacy instruction arm is being served.
     */
    readonly canExecuteScripts: boolean
}

/**
 * Injected typecheck seam (spec §4.8): the server wires the real
 * `ts.LanguageService` gate; a bundle without `typescript` beside it (the
 * distributed CLI) leaves it unset and gets the contract lints only. Kept as
 * an injection so this module never imports compile-gate — a static edge would
 * drag `typescript` and the multi-MB SDK declarations into every bundle.
 */
export interface CompileGate {
    check(source: string): Promise<CompileGateResult>
}

/**
 * Host-side inner-tool dispatch seam for the fast path (spec §4.2). The exec
 * host implements both methods over the shared `dispatchInnerTool` pipeline so
 * a fast-pathed script behaves byte-identically to `call` — including UI-app
 * payloads and inner-tool analytics attribution.
 */
export interface InnerToolDispatcher {
    /**
     * Whether the tool exists in this session's catalog and the input passes
     * its schema. Checked before committing to the fast path — a miss falls
     * through to the sandbox instead of surfacing a fast-path-specific error.
     */
    canDispatch(toolName: string, input: Record<string, unknown>): boolean
    /** Run the shared dispatch pipeline. Handler errors propagate to the caller. */
    dispatch(toolName: string, input: Record<string, unknown>, opts?: { suppressUiPayload?: boolean }): Promise<unknown>
}

export interface CodeExecutionRuntimeDeps {
    /** Authenticated fetch against the real API — the transports' passthrough. */
    realFetch: FetchLike
    /** User identity namespacing plan-store keys — a plan id only resolves for the identity that minted it. */
    getSub: () => Promise<string>
    /**
     * Active project for this session — the same resolution the tool handlers
     * use (`stateManager.getProjectId`), so fast-pathed and sandboxed scripts
     * can never implicitly target different projects, and plans are pinned to
     * the project the user confirmed them against.
     */
    getProjectId: () => Promise<string>
    /** Active organization, as the sandboxed client's default; failures degrade to the SDK's own resolution. */
    getOrgId?: () => Promise<string>
    planStore: PlanStore
    /** Sandbox for arbitrary scripts; absent on fast-path-only processes (spec §4.2). */
    executor?: SandboxExecutor
    classifierTable: ClassifierTable
    /** Typecheck gate; when absent, `run` falls back to the contract lints and flags the skipped typecheck. */
    compileGate?: CompileGate
    /** Fast-path dispatch seam; when absent, every script takes the sandbox path. */
    toolDispatcher?: InnerToolDispatcher
    /** Test seam; defaults to the generated artifact. */
    discoveryIndex?: DiscoveryIndex
    timeoutMs?: number
}

// Mirror compile-gate's reserved 90xxx lint codes without importing it (see `CompileGate`).
const MISSING_EXPORT_DEFAULT_CODE = 90001
const REQUIRE_FORBIDDEN_CODE = 90002

/** Gate-less fallback: exactly the two contract lints the full gate also applies. */
function lintScriptContract(source: string): CompileGateResult {
    const diagnostics: CompileDiagnostic[] = []

    const requireMatch = /\brequire\s*\(/.exec(source)
    if (requireMatch) {
        const before = source.slice(0, requireMatch.index)
        diagnostics.push({
            line: before.split('\n').length,
            character: requireMatch.index - before.lastIndexOf('\n'),
            message: "require() is not available in scripts — use `import { client } from '@posthog/sdk'`.",
            code: REQUIRE_FORBIDDEN_CODE,
        })
    }

    if (!/\bexport\s+default\b/.test(source)) {
        diagnostics.push({
            line: 1,
            character: 1,
            message: 'Script must `export default` the value to return (e.g. `export default { updated }`).',
            code: MISSING_EXPORT_DEFAULT_CODE,
        })
    }

    return diagnostics.length === 0 ? { ok: true } : { ok: false, diagnostics }
}

/** Serialize a script result, hard-capped so a huge payload cannot flood context. */
function serializeCapped(value: unknown): string {
    let text: string
    try {
        text = JSON.stringify(value, null, 1) ?? 'undefined'
    } catch {
        text = String(value)
    }
    if (text.length <= TOKEN_CHAR_LIMIT) {
        return text
    }
    return `${text.slice(0, TOKEN_CHAR_LIMIT)}\n…[output truncated — have the script return a smaller summary]`
}

function consoleSection(consoleOutput: string[]): string[] {
    return consoleOutput.length > 0 ? ['Console:', consoleOutput.join('\n')] : []
}

/** The single SDK argument object IS the tool input, key-for-key (`{}` when absent) — anything else is not call-shaped. */
function callInputFromArgs(args: unknown[]): Record<string, unknown> | null {
    if (args.length === 0) {
        return {}
    }
    const [arg] = args
    if (typeof arg !== 'object' || arg === null || Array.isArray(arg)) {
        return null
    }
    return { ...(arg as Record<string, unknown>) }
}

/**
 * Substitute `{param}` path segments from scalar input fields, for display
 * only. Segments the values don't carry stay as-is.
 */
function fillPathTemplate(template: string, input: Record<string, unknown>): string {
    return template.replace(/\{(\w+)\}/g, (placeholder, name: string) => {
        const value = input[name]
        return typeof value === 'string' || typeof value === 'number' ? String(value) : placeholder
    })
}

/** Render the degenerate one-call plan: tool title, operation kind, pretty-printed input, destructive marker loud. */
function renderCallPlan(args: {
    method: DiscoveryMethod
    operation: ClassifierOperation
    input: Record<string, unknown>
    softDelete: boolean
}): string {
    const { method, operation, input, softDelete } = args
    const kind =
        operation.method === 'DELETE' || softDelete ? 'DELETE' : operation.method === 'POST' ? 'CREATE' : 'UPDATE'
    const lines = ['Plan: 1 mutation(s).', '', `${kind} ${operation.objectType} — ${method.title} (${method.id})`]
    if (operation.destructive) {
        lines.push('!! DESTRUCTIVE: this permanently deletes data and cannot be undone.')
    }
    lines.push('Input:', JSON.stringify(input, null, 2))
    return lines.join('\n')
}

export function createCodeExecutionRuntime(deps: CodeExecutionRuntimeDeps): CodeExecutionRuntime {
    const classifier = createClassifier(deps.classifierTable)
    const timeoutMs = deps.timeoutMs ?? DEFAULT_SCRIPT_TIMEOUT_MS
    const operationsById = new Map(deps.classifierTable.operations.map((operation) => [operation.id, operation]))

    // Exact-case method lookup for the fast path — `createDiscovery`'s internal
    // map is lowercased for forgiving `types` queries, but dispatching a
    // wrongly-cased method the compile gate would reject is a widening.
    let methodsById: Map<string, DiscoveryMethod> | null = null
    const getMethodsById = async (): Promise<Map<string, DiscoveryMethod>> => {
        if (!methodsById) {
            const index = deps.discoveryIndex ?? (await getGeneratedDiscoveryIndex())
            methodsById = new Map(index.methods.map((method) => [method.id, method]))
        }
        return methodsById
    }

    const storePlan = async (stored: StoredPlan): Promise<string> => {
        let phrase = generatePlanPhrase()
        // ~1-in-2B collision guard: bounded regenerate, then let the last put win.
        for (let attempt = 0; attempt < 3; attempt++) {
            if ((await deps.planStore.get(`${stored.sub}:${phrase}`)) === null) {
                break
            }
            phrase = generatePlanPhrase()
        }
        await deps.planStore.put(`${stored.sub}:${phrase}`, stored, PLAN_PHRASE_TTL_SECONDS)
        return phrase
    }

    const confirmationSection = (phrase: string, projectId: string): string[] => [
        `Plan created against project ${projectId} — apply requires the same active project.`,
        `Show this plan to the user and get their explicit confirmation. Only after they confirm, run:\napply ${phrase}`,
        `The plan id is single-use and expires in ${Math.floor(PLAN_PHRASE_TTL_SECONDS / 60)} minutes.`,
    ]

    /**
     * Session default project/org for a sandbox execution — the same source
     * the tool handlers read, so the two execution stacks always agree on the
     * target tenant. Project resolution failures propagate (a session without
     * project context can't run scripts, exactly as it can't call tools); org
     * resolution is best-effort.
     */
    const resolveSandboxScope = async (): Promise<{ projectId: string; organizationId?: string }> => {
        const projectId = await deps.getProjectId()
        const organizationId = deps.getOrgId ? await deps.getOrgId().catch(() => undefined) : undefined
        return organizationId !== undefined ? { projectId, organizationId } : { projectId }
    }

    /**
     * The no-sandbox fast path (spec §4.2). A pure optimization: any miss —
     * shape, resolution, mapping, classification, or validation — returns
     * `null` and the caller falls through to the sandbox path. Never surfaces
     * a fast-path-specific error.
     */
    const tryFastPath = async (source: string): Promise<RunOutcome | null> => {
        const dispatcher = deps.toolDispatcher
        if (!dispatcher) {
            return null
        }
        const match = await matchFastPath(source)
        if (!match) {
            return null
        }
        const method = (await getMethodsById()).get(match.methodId)
        if (!method?.toolName) {
            return null
        }
        const input = callInputFromArgs(match.args)
        if (input === null) {
            return null
        }
        const toolName = method.toolName
        if (!dispatcher.canDispatch(toolName, input)) {
            return null
        }

        const dispatchRead = async (): Promise<RunOutcome> => ({
            output: await dispatcher.dispatch(toolName, input),
            meta: { fastPath: true, innerToolName: toolName, status: 'read_only' },
        })

        const operation = operationsById.get(match.methodId)
        if (!operation) {
            // Fail closed like the plan classifier: an unknown method goes to
            // the sandbox. The `query.*` wrappers are the one known gap — all
            // reads through the single POST /query/ classifier entry.
            return match.methodId.startsWith('query.') ? dispatchRead() : null
        }
        if (operation.readOnly) {
            return dispatchRead()
        }

        // Mutating fast-path calls do not bypass plan/apply (spec §4.2): store
        // a degenerate one-call plan under the same key/TTL/consume semantics,
        // pinned to the active project — apply replays through the tool handler,
        // which resolves the project from apply-time session state, so without
        // the pin a project switch between plan and apply would land the change
        // in a project the user never confirmed.
        const projectId = await deps.getProjectId()
        const softDelete = operation.softDelete && input.deleted === true
        const mutation: RecordedMutation = {
            sequence: 0,
            operationId: match.methodId,
            method: operation.method,
            path: fillPathTemplate(operation.pathTemplate, { project_id: projectId, ...input }),
            body: input,
            softDelete,
            destructive: operation.destructive,
            objectType: operation.objectType,
            sentinels: [],
        }
        const plan = buildPlan([mutation], source)
        const sub = await deps.getSub()
        const phrase = await storePlan({ kind: 'call', plan, sub, projectId, call: { toolName, input } })
        const output = [
            'The script wants to make changes. Nothing has been applied yet.',
            renderCallPlan({ method, operation, input, softDelete }),
            ...confirmationSection(phrase, projectId),
        ].join('\n\n')
        return {
            output,
            meta: { fastPath: true, innerToolName: toolName, status: 'plan_issued', planMutations: 1, planId: phrase },
        }
    }

    /** Apply a degenerate call plan: replay the call through the tool handler — no sandbox, no enforce transport. */
    const applyCallPlan = async (stored: StoredCallPlan): Promise<ApplyOutcome> => {
        const recorded = stored.plan.mutations[0]
        const outcomeBase = {
            sequence: 0,
            operationId: recorded?.operationId ?? null,
            method: recorded?.method ?? '',
            path: recorded?.path ?? '',
        }
        const dispatcher = deps.toolDispatcher
        if (!dispatcher) {
            // Structurally unreachable: a call plan is only minted with a dispatcher wired.
            return {
                output: [
                    'Apply failed: tool dispatch is not available in this environment — nothing was applied.',
                    REPLAN_HINT,
                ].join('\n\n'),
                meta: { status: 'failed' },
            }
        }
        try {
            const output = await dispatcher.dispatch(stored.call.toolName, stored.call.input, {
                suppressUiPayload: true,
            })
            const outcomes: MutationOutcome[] = [{ ...outcomeBase, status: 'applied' }]
            return {
                output: [
                    'Applied.',
                    renderReceiptText(outcomes),
                    'Output:',
                    typeof output === 'string' ? output : serializeCapped(output),
                ].join('\n\n'),
                meta: { status: 'applied' },
            }
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error)
            const outcomes: MutationOutcome[] = [{ ...outcomeBase, status: 'failed', error: message }]
            return {
                output: [`Apply failed: ${message}`, 'Receipt:', renderReceiptText(outcomes), REPLAN_HINT].join('\n\n'),
                meta: { status: 'failed' },
            }
        }
    }

    return {
        canExecuteScripts: deps.executor !== undefined,

        async run(source) {
            const fastPath = await tryFastPath(source)
            if (fastPath !== null) {
                return fastPath
            }

            const gate = deps.compileGate ? await deps.compileGate.check(source) : lintScriptContract(source)
            if (!gate.ok) {
                return {
                    output: JSON.stringify({
                        status: 'compile_error',
                        diagnostics: gate.diagnostics,
                        hint: 'Fix the script and run it again. Use "types <symbol>" to inspect SDK declarations.',
                    }),
                    meta: { fastPath: false, status: 'compile_error' },
                }
            }
            const typecheckNote = deps.compileGate
                ? []
                : ['Note: TypeScript typecheck was skipped in this environment — type errors surface at runtime.']

            const executor = deps.executor
            if (!executor) {
                // Fast-path-only process (spec §4.2): the verb stays available —
                // call-shaped scripts dispatched above — but anything needing
                // real script execution gets a targeted redirect, not a crash.
                return {
                    output: [
                        'This script needs the sandbox executor, which is not available on this server yet — only single-call scripts run here.',
                        "Write exactly one SDK call with literal arguments (import { client } from '@posthog/sdk' then export default await client.<domain>.<method>({ ... })), split multi-step work into separate runs, or use `sql <hogql>` for queries.",
                    ].join('\n'),
                    meta: { fastPath: false, status: 'sandbox_unavailable' },
                }
            }

            const scope = await resolveSandboxScope()
            const sentinels = createSentinelFactory(randomUUID())
            const planTransport = createPlanTransport({ realFetch: deps.realFetch, classifier, sentinels })
            const execution = await executor.execute({
                source,
                transportFetch: planTransport.fetch,
                timeoutMs,
                ...scope,
            })
            const mutations = planTransport.getMutations()

            if (execution.error) {
                // A failed plan pass is never confirmable — even when mutations
                // were recorded before the failure, no plan id is issued.
                return {
                    output: [
                        `Script failed: ${execution.error.message}`,
                        ...(mutations.length > 0
                            ? [
                                  `Before failing it attempted ${mutations.length} mutation(s) (none were applied):`,
                                  renderPlanText(buildPlan(mutations, source)),
                              ]
                            : []),
                        ...consoleSection(execution.consoleOutput),
                        ...typecheckNote,
                    ].join('\n\n'),
                    meta: { fastPath: false, status: 'failed' },
                }
            }

            if (mutations.length === 0) {
                // Zero mutations → the plan run was the real run.
                return {
                    output: [
                        `Output:`,
                        serializeCapped(execution.output),
                        ...consoleSection(execution.consoleOutput),
                        ...typecheckNote,
                    ].join('\n\n'),
                    meta: { fastPath: false, status: 'read_only' },
                }
            }

            const plan = buildPlan(mutations, source)
            const sub = await deps.getSub()
            const phrase = await storePlan({ kind: 'script', script: source, plan, sub, projectId: scope.projectId })

            return {
                output: [
                    'The script wants to make changes. Nothing has been applied yet.',
                    renderPlanText(plan),
                    'Provisional output (computed against synthetic responses — placeholder ids like negative numbers are not real):',
                    serializeCapped(execution.output),
                    ...consoleSection(execution.consoleOutput),
                    ...confirmationSection(phrase, scope.projectId),
                    ...typecheckNote,
                ].join('\n\n'),
                meta: { fastPath: false, status: 'plan_issued', planMutations: mutations.length, planId: phrase },
            }
        },

        async apply(planId) {
            const sub = await deps.getSub()
            const phrase = normalizePlanPhrase(planId)
            // Consume before executing: a failed apply still requires a re-plan.
            const stored = await deps.planStore.consume(`${sub}:${phrase}`)
            if (stored === 'consumed') {
                return {
                    output: `This plan has already been applied — a plan id is single-use. ${REPLAN_HINT}`,
                    meta: { status: 'already_applied' },
                }
            }
            if (stored === null) {
                return {
                    output: `Plan not found — it may have expired (10 minutes), already been applied, or the id was mistyped. Nothing was applied. ${REPLAN_HINT}`,
                    meta: { status: 'not_found' },
                }
            }
            if (stored.sub !== sub) {
                // Belt and braces: the key embeds sub, so this is structurally unreachable.
                return {
                    output: `Plan does not belong to this user — nothing was applied. ${REPLAN_HINT}`,
                    meta: { status: 'not_found' },
                }
            }

            // The user confirmed changes to the plan-time project; executing
            // under a different active project would land them somewhere they
            // never reviewed (id-addressed calls 404, but creates and
            // key-addressed updates would succeed silently in the wrong
            // project). The `undefined` guard tolerates plans stored before
            // the pin existed.
            const currentProjectId = await deps.getProjectId()
            if (stored.projectId !== undefined && stored.projectId !== currentProjectId) {
                return {
                    output: [
                        `The active project changed since this plan was created (project ${stored.projectId} → ${currentProjectId}) — the apply was aborted and nothing was applied.`,
                        `Switch back to project ${stored.projectId}, or re-run the script under the current project to get a fresh plan.`,
                    ].join('\n\n'),
                    meta: { status: 'diverged' },
                }
            }

            if (stored.kind === 'call') {
                return applyCallPlan(stored)
            }

            const executor = deps.executor
            if (!executor) {
                // Structurally unreachable on a single process (script plans are
                // only minted where an executor exists), but a shared plan store
                // could surface one on a fast-path-only replica — fail loudly
                // rather than crash.
                return {
                    output: [
                        'Apply failed: this server cannot execute script plans (no sandbox executor is available) — nothing was applied.',
                        REPLAN_HINT,
                    ].join('\n\n'),
                    meta: { status: 'failed' },
                }
            }

            const enforce = createEnforceTransport({ realFetch: deps.realFetch, plan: stored.plan, classifier })
            // The divergence error surfaces inside the script (the SDK rethrows
            // it), so the executor reports it as a generic script failure —
            // capture it at the transport seam to answer with the typed message.
            // A ref object (not a bare `let`) keeps control-flow analysis from
            // narrowing the closure-assigned value to its initializer.
            const divergenceRef: { current: PlanDivergenceError | null } = { current: null }
            const transportFetch: FetchLike = async (input, init) => {
                try {
                    return await enforce.fetch(input, init)
                } catch (error) {
                    if (error instanceof PlanDivergenceError && !divergenceRef.current) {
                        divergenceRef.current = error
                    }
                    throw error
                }
            }

            const execution = await executor.execute({
                source: stored.script,
                transportFetch,
                timeoutMs,
                ...(await resolveSandboxScope()),
            })
            const receipt = enforce.getReceipt()

            const divergence = divergenceRef.current
            if (divergence) {
                const attempted = divergence.attempted
                return {
                    output: [
                        'The world changed since you confirmed — the script attempted a mutation that is not in the confirmed plan, and the apply was aborted.',
                        `Divergent call: ${attempted.method} ${attempted.path}`,
                        'Receipt:',
                        renderReceiptText(receipt),
                        REPLAN_HINT,
                    ].join('\n\n'),
                    meta: { status: 'diverged' },
                }
            }

            if (execution.error) {
                return {
                    output: [
                        `Apply failed partway: ${execution.error.message}`,
                        'Receipt:',
                        renderReceiptText(receipt),
                        `Re-run the script to plan the remaining work — the fresh plan will cover only what is left.`,
                        ...consoleSection(execution.consoleOutput),
                    ].join('\n\n'),
                    meta: { status: 'failed' },
                }
            }

            return {
                output: [
                    'Applied.',
                    renderReceiptText(receipt),
                    'Output:',
                    serializeCapped(execution.output),
                    ...consoleSection(execution.consoleOutput),
                ].join('\n\n'),
                meta: { status: 'applied' },
            }
        },
    }
}
