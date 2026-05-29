/**
 * Injected handle to the agent-memory engine, mirroring posthog-client.ts.
 * The runner constructs a `Memory` (backed by the agent_runtime_queue Pool +
 * a Recaller) at boot and calls `setMemory`; memory tools call `getMemory`.
 * Kept here so each tool's run() stays a clean, unit-testable one-call function.
 */

import type { Memory } from '@posthog/agent-shared'

let MEMORY: Memory | null = null

export function setMemory(memory: Memory): void {
    MEMORY = memory
}

export function getMemory(): Memory {
    if (!MEMORY) {
        throw new Error('Memory not configured. Call setMemory first (the runner wires it at boot).')
    }
    return MEMORY
}
