/**
 * Runtime facade behind the code-execution exec verbs. `exec.ts` only sees
 * this interface; everything stateful — plan transports, token codec, plan
 * store, nonce ledger, discovery index, executor — is wired here.
 *
 * Flow (spec §3.6): `run` compiles, executes in plan mode, and either returns
 * results directly (zero mutations) or a rendered plan + signed single-use
 * token. `apply` verifies the token, burns the nonce, reloads the stored
 * script, and re-runs it live with the confirmed plan enforced as a contract.
 */

import { randomUUID } from 'node:crypto'

import {
    buildPlan,
    type ClassifierTable,
    createClassifier,
    createEnforceTransport,
    createPlanTransport,
    createSentinelFactory,
    decodePlanToken,
    encodePlanToken,
    type FetchLike,
    PLAN_TOKEN_TTL_SECONDS,
    PlanDivergenceError,
    type PlanStore,
    renderPlanText,
    renderReceiptText,
} from '@/lib/code-exec'
import { NonceLedger, SignedStateAlreadyConsumed, type SignedStateCodec } from '@/lib/signed-state'

import { TOKEN_CHAR_LIMIT } from '../schema-utils'
import { checkScript } from './compile-gate'
import { createDiscovery, type Discovery, type DiscoveryIndex, getGeneratedDiscoveryIndex } from './discovery'
import type { SandboxExecutor } from './executor'

/** Wall-clock budget for one script execution (plan or apply pass). */
const DEFAULT_SCRIPT_TIMEOUT_MS = 30_000

const REPLAN_HINT = 'Re-run the script with "run <source>" to get a fresh plan and confirm it again.'

export interface CodeExecutionRuntime {
    searchTypes(query: string): Promise<string>
    showTypes(target: string): Promise<string>
    run(source: string): Promise<string>
    apply(token: string): Promise<string>
}

export interface CodeExecutionRuntimeDeps {
    /** Authenticated fetch against the real API — the transports' passthrough. */
    realFetch: FetchLike
    /** User identity bound into plan tokens — the same identity `confirmed_action` signs. */
    getSub: () => Promise<string>
    /** Purpose-bound plan-token codec (`createPlanTokenCodec`). */
    codec: SignedStateCodec
    planStore: PlanStore
    /** Single-use enforcement for apply tokens; `null` skips it (memory-backed dev). */
    nonceLedger: NonceLedger | null
    /** Resolved API key scopes, for scope-annotated discovery. */
    sessionScopes: string[]
    executor: SandboxExecutor
    classifierTable: ClassifierTable
    /** Test seam; defaults to the generated artifact. */
    discoveryIndex?: DiscoveryIndex
    timeoutMs?: number
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

export function createCodeExecutionRuntime(deps: CodeExecutionRuntimeDeps): CodeExecutionRuntime {
    const classifier = createClassifier(deps.classifierTable)
    const timeoutMs = deps.timeoutMs ?? DEFAULT_SCRIPT_TIMEOUT_MS

    let discovery: Discovery | null = deps.discoveryIndex ? createDiscovery(deps.discoveryIndex) : null
    const getDiscovery = async (): Promise<Discovery> => {
        discovery ??= createDiscovery(await getGeneratedDiscoveryIndex())
        return discovery
    }

    return {
        async searchTypes(query) {
            return (await getDiscovery()).search(query, deps.sessionScopes)
        },

        async showTypes(target) {
            return (await getDiscovery()).show(target, deps.sessionScopes)
        },

        async run(source) {
            const gate = await checkScript(source)
            if (!gate.ok) {
                return JSON.stringify({
                    status: 'compile_error',
                    diagnostics: gate.diagnostics,
                    hint: 'Fix the script and run it again. Use "types show <symbol>" to inspect SDK declarations.',
                })
            }

            const sentinels = createSentinelFactory(randomUUID())
            const planTransport = createPlanTransport({ realFetch: deps.realFetch, classifier, sentinels })
            const execution = await deps.executor.execute({
                source,
                transportFetch: planTransport.fetch,
                timeoutMs,
            })
            const mutations = planTransport.getMutations()

            if (execution.error) {
                // A failed plan pass is never confirmable — even when mutations
                // were recorded before the failure, no token is issued.
                return [
                    `Script failed: ${execution.error.message}`,
                    ...(mutations.length > 0
                        ? [
                              `Before failing it attempted ${mutations.length} mutation(s) (none were applied):`,
                              renderPlanText(buildPlan(mutations, source)),
                          ]
                        : []),
                    ...consoleSection(execution.consoleOutput),
                ].join('\n\n')
            }

            if (mutations.length === 0) {
                // Zero mutations → the plan run was the real run.
                return [`Output:`, serializeCapped(execution.output), ...consoleSection(execution.consoleOutput)].join(
                    '\n\n'
                )
            }

            const plan = buildPlan(mutations, source)
            const sub = await deps.getSub()
            await deps.planStore.put(plan.scriptHash, { script: source, plan, sub }, PLAN_TOKEN_TTL_SECONDS)
            const { token } = await encodePlanToken(deps.codec, {
                sub,
                planHash: plan.planHash,
                scriptHash: plan.scriptHash,
            })

            return [
                'The script wants to make changes. Nothing has been applied yet.',
                renderPlanText(plan),
                'Provisional output (computed against synthetic responses — placeholder ids like negative numbers are not real):',
                serializeCapped(execution.output),
                ...consoleSection(execution.consoleOutput),
                `Show this plan to the user and get their explicit confirmation. Only after they confirm, run:\napply ${token}`,
                `The plan token is single-use and expires in ${Math.floor(PLAN_TOKEN_TTL_SECONDS / 60)} minutes.`,
            ].join('\n\n')
        },

        async apply(token) {
            const sub = await deps.getSub()
            const decoded = await decodePlanToken(deps.codec, token, sub)
            if (!decoded.ok) {
                if (decoded.reason === 'expired') {
                    // Never auto-apply on an expired confirmation.
                    return `Plan expired — nothing was applied. ${REPLAN_HINT}`
                }
                return `Plan token rejected (${decoded.kind}): ${decoded.message}. Nothing was applied. ${REPLAN_HINT}`
            }

            if (deps.nonceLedger) {
                try {
                    await deps.nonceLedger.consume(decoded.nonce, decoded.secondsUntilExpiry)
                } catch (error) {
                    if (error instanceof SignedStateAlreadyConsumed) {
                        return `This plan has already been applied — a plan token is single-use. ${REPLAN_HINT}`
                    }
                    throw error
                }
            }

            const stored = await deps.planStore.get(decoded.scriptHash)
            if (!stored) {
                return `Plan expired — the stored script is gone and nothing was applied. ${REPLAN_HINT}`
            }
            if (
                stored.plan.planHash !== decoded.planHash ||
                stored.plan.scriptHash !== decoded.scriptHash ||
                stored.sub !== decoded.sub
            ) {
                return `Plan token does not match the stored plan — nothing was applied. ${REPLAN_HINT}`
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

            const execution = await deps.executor.execute({
                source: stored.script,
                transportFetch,
                timeoutMs,
            })
            const receipt = enforce.getReceipt()

            const divergence = divergenceRef.current
            if (divergence) {
                const attempted = divergence.attempted
                return [
                    'The world changed since you confirmed — the script attempted a mutation that is not in the confirmed plan, and the apply was aborted.',
                    `Divergent call: ${attempted.method} ${attempted.path}`,
                    'Receipt:',
                    renderReceiptText(receipt),
                    REPLAN_HINT,
                ].join('\n\n')
            }

            if (execution.error) {
                return [
                    `Apply failed partway: ${execution.error.message}`,
                    'Receipt:',
                    renderReceiptText(receipt),
                    `Re-run the script to plan the remaining work — the fresh plan will cover only what is left.`,
                    ...consoleSection(execution.consoleOutput),
                ].join('\n\n')
            }

            return [
                'Applied.',
                renderReceiptText(receipt),
                'Output:',
                serializeCapped(execution.output),
                ...consoleSection(execution.consoleOutput),
            ].join('\n\n')
        },
    }
}
