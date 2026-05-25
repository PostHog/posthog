import { DockerToolSandbox } from '@repo/ass-sandbox'
import type { SandboxTracker, SecretBroker, ToolSandbox } from '@repo/ass-sandbox'
import { dirname, join } from 'node:path'

import type { SandboxInstancesRepository } from '@posthog/agent-core'

export type ToolSandboxKind = 'docker' | 'modal'

/** The slice of a compiled-bundle agent the tool-sandbox factory needs. */
interface BundledAgent {
    tools: Array<{ yaml: { id: string }; compiledJs: Uint8Array }>
}

/**
 * Per-session context needed to attribute durable SandboxInstance rows. The
 * agent-runner has all three values from the resolved revision; passing them
 * explicitly keeps `@repo/ass-sandbox` ignorant of Django identifiers.
 */
export interface SandboxAttribution {
    teamId: number
    applicationId: string
    revisionId: string
}

/**
 * Build the durable-tracker the sandbox provider calls into. Inserts a row in
 * `provisioning` on acquire and walks it through `ready` → `terminated` as the
 * sandbox's life unfolds. All updates are best-effort; tracker failures log
 * but never kill the session (the sandbox itself is still functional).
 */
function buildSandboxTracker(
    repo: SandboxInstancesRepository,
    attr: SandboxAttribution,
    log: (line: string) => void
): SandboxTracker {
    return {
        async onAcquire() {
            let row
            try {
                row = await repo.create({
                    teamId: attr.teamId,
                    applicationId: attr.applicationId,
                    revisionId: attr.revisionId,
                })
            } catch (err) {
                log(`[sandbox-tracker] create failed: ${String(err)}`)
                return null
            }
            return {
                async ready(providerSandboxId: string) {
                    await repo.markReady(row.id, providerSandboxId)
                },
                async touch() {
                    await repo.touch(row.id)
                },
                async fail(message: string) {
                    await repo.markFailed(row.id, message)
                },
                async release() {
                    await repo.markTerminated(row.id)
                },
            }
        },
    }
}

/**
 * Pick the tool-sandbox provider for the deployed runner.
 *
 * `AGENT_RUNNER_TOOL_SANDBOX` is the explicit override (`docker` | `modal`).
 * With it unset, Modal is selected when its credentials (`MODAL_TOKEN_ID` +
 * `MODAL_TOKEN_SECRET`) are present, otherwise Docker. `in-process` is
 * deliberately not selectable — the deployed runner must never execute
 * customer tool code unsandboxed.
 */
export function selectToolSandboxKind(env: NodeJS.ProcessEnv = process.env): ToolSandboxKind {
    const explicit = env.AGENT_RUNNER_TOOL_SANDBOX?.trim().toLowerCase()
    if (explicit === 'docker' || explicit === 'modal') {
        return explicit
    }
    if (explicit) {
        throw new Error(`AGENT_RUNNER_TOOL_SANDBOX must be "docker" or "modal" — got "${explicit}"`)
    }
    return env.MODAL_TOKEN_ID && env.MODAL_TOKEN_SECRET ? 'modal' : 'docker'
}

/** Absolute path to @repo/ass-sandbox's container-runner script (baked into the Docker image). */
function containerRunnerPath(): string {
    return join(dirname(require.resolve('@repo/ass-sandbox')), 'container-runner.js')
}

/**
 * Build the `makeToolSandbox` factory `runSession` expects, for an agent loaded
 * from a compiled bundle. The factory receives the session's `SecretBroker`.
 *
 * When a `sandboxInstances` repository is provided alongside the session's
 * Django identifiers, the chosen provider also writes
 * `AgentApplicationSandboxInstance` rows for durable lifecycle tracking — the
 * janitor uses those to reap sandboxes whose worker died mid-session.
 */
export function makeToolSandboxFactory(
    agent: BundledAgent,
    log: (line: string) => void,
    tracking?: {
        repo: SandboxInstancesRepository
        attribution: SandboxAttribution
    }
): (broker: SecretBroker) => ToolSandbox {
    const kind = selectToolSandboxKind()
    if (kind === 'modal') {
        throw new Error('AGENT_RUNNER_TOOL_SANDBOX=modal — ModalToolSandbox is not implemented yet; use docker')
    }
    const tools = agent.tools.map((t) => ({ id: t.yaml.id, compiledJs: t.compiledJs }))
    const runnerPath = containerRunnerPath()
    const tracker = tracking ? buildSandboxTracker(tracking.repo, tracking.attribution, log) : undefined
    return (broker) => new DockerToolSandbox({ tools, broker, containerRunnerPath: runnerPath, log, tracker })
}
