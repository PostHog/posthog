/**
 * SDK executor export. Lives at its own subpath because it imports
 * `@anthropic-ai/claude-agent-sdk` (ESM) — jest's CJS transformer can't
 * load that without `transformIgnorePatterns`, so consumers (e.g. the
 * isolated test suite) that don't need it stay clean.
 *
 * App tests import explicitly: `import { AssServerExecutor } from
 * '@posthog/agent-runner/executor-sdk'`.
 */
export { AssServerExecutor } from './ass-server-executor'
