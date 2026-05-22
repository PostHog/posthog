import { DockerToolSandbox } from '@repo/ass-sandbox'
import type { SecretBroker, ToolSandbox } from '@repo/ass-sandbox'
import { dirname, join } from 'node:path'

export type ToolSandboxKind = 'docker' | 'modal'

/** The slice of a compiled-bundle agent the tool-sandbox factory needs. */
interface BundledAgent {
    tools: Array<{ yaml: { id: string }; compiledJs: Uint8Array }>
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
 */
export function makeToolSandboxFactory(
    agent: BundledAgent,
    log: (line: string) => void
): (broker: SecretBroker) => ToolSandbox {
    const kind = selectToolSandboxKind()
    if (kind === 'modal') {
        throw new Error('AGENT_RUNNER_TOOL_SANDBOX=modal — ModalToolSandbox is not implemented yet; use docker')
    }
    const tools = agent.tools.map((t) => ({ id: t.yaml.id, compiledJs: t.compiledJs }))
    const runnerPath = containerRunnerPath()
    return (broker) => new DockerToolSandbox({ tools, broker, containerRunnerPath: runnerPath, log })
}
