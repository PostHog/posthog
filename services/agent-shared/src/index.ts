/**
 * Public surface of @posthog/agent-shared. Re-exports everything callers
 * (runner, ingress, janitor, tests) need. Internal organization lives under
 * `src/<concern>/`:
 *   - spec/         — agent spec, tool ref, session shape (zod + TS types)
 *   - storage/      — bundle storage interfaces + impls
 *   - persistence/  — Postgres schema, session queue, revision store, identities
 *   - sandbox/      — sandbox interface + Docker/Modal/in-process pools + the
 *                     durable instance log + the secret broker
 *   - runtime/      — bus, log sink, logger, encryption — runtime support that
 *                     isn't tied to one persistence backend
 */

export * from './spec/spec'
export * from './spec/summarize-conversation'
export * from './spec/tool'
export * from './spec/framework-preamble'
export * from './spec/system-prompt'

export * from './storage/bundle'
export * from './storage/memory-bundle-store'
export * from './storage/fs-bundle-store'
export * from './storage/s3-bundle-store'

export * from './persistence/queue'
export * from './persistence/revision-store'
export * from './persistence/identity-store'
export * from './persistence/integration-store'
export * from './persistence/approval-store'
export * from './persistence/create-pool'
export * from './persistence/pg-queue'
export * from './persistence/pg-revision-store'
export * from './persistence/pg-approval-store'

export * from './sandbox/sandbox'
export * from './sandbox/sandbox-inprocess'
export * from './sandbox/sandbox-docker'
export * from './sandbox/sandbox-modal'
export * from './sandbox/sandbox-selector'
export * from './sandbox/sandbox-instance-store'
export * from './sandbox/sandbox-terminator'
export * from './sandbox/secret-broker'

export * from './runtime/analytics-sink'
export * from './runtime/bus'
export * from './runtime/credential-broker'
export * from './runtime/pg-credential-broker'
export * from './runtime/log-sink'
export * from './runtime/logger'
export * from './runtime/process-handlers'
export * from './runtime/encryption'
export * from './runtime/team-api-key-resolver'
export * from './runtime/gateway-client'

export * from './config/platform'

export * from './memory'
