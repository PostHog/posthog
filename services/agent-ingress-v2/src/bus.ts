/**
 * Re-exports the session event bus from agent-shared-v2. The interface + impls
 * moved to shared so the runner can publish lifecycle events without ingress
 * being on its import path.
 */

export {
    MemorySessionEventBus,
    NoopSessionEventBus,
    type SessionEvent,
    type SessionEventBus,
    type SessionEventKind,
} from '@posthog/agent-shared-v2'
