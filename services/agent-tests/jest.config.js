/**
 * agent-tests runs end-to-end against the local stack `hogli start` provides:
 * PostHog Postgres, the queue Postgres, Kafka, ClickHouse. Tests boot
 * agent-ingress + agent-runner in-process and assert through real wires.
 *
 *   pnpm --filter @posthog/agent-tests test
 *
 * Skipped if the stack isn't reachable — the harness probes on startup and
 * throws a clear error pointing at hogli.
 */
/** @type {import('jest').Config} */
module.exports = {
    preset: 'ts-jest',
    testEnvironment: 'node',
    testMatch: ['<rootDir>/src/cases/**/*.test.ts'],
    // Real DB + Kafka + ClickHouse round trips need more headroom than unit tests.
    testTimeout: 30_000,
    // Boot one shared ingress + runner for the entire test run. The router
    // executor dispatches per-app via `__TEST_EXECUTOR` in encrypted_env,
    // so every suite hits the same bins. Cuts suite startup from ~5s × N
    // suites to ~5s total. See src/harness/global-setup.ts.
    globalSetup: '<rootDir>/src/harness/global-setup.ts',
    globalTeardown: '<rootDir>/src/harness/global-teardown.ts',
    // Force serial execution. Suites are designed to share the cluster
    // and isolate via unique app slugs; parallel workers would each open
    // their own pools (fine) but per-test cleanup ordering across
    // workers is harder to reason about. Local dev cost is already low.
    maxWorkers: 1,
    moduleNameMapper: {
        // @repo/ass-server is workspace-linked from agent-stack; the dual
        // ESM+CJS bundle's `exports` field isn't followed by jest's CJS
        // resolver, so map subpaths to the `.cjs` files explicitly.
        '^@repo/ass-server$': '<rootDir>/node_modules/@repo/ass-server/dist/index.cjs',
        '^@repo/ass-server/(.*)$': '<rootDir>/node_modules/@repo/ass-server/dist/$1.cjs',
        // ass-bundler + ass-config emit dual ESM/CJS; map subpaths to the
        // CJS variant so jest's CJS resolver loads them natively without
        // needing ESM-aware transform.
        '^@repo/ass-bundler/(.*)$': '<rootDir>/node_modules/@repo/ass-bundler/dist/$1.cjs',
        '^@repo/ass-config/(.*)$': '<rootDir>/node_modules/@repo/ass-config/dist/$1.cjs',
    },
    transform: {
        '^.+\\.tsx?$': ['ts-jest', { tsconfig: '<rootDir>/tsconfig.json' }],
    },
}
