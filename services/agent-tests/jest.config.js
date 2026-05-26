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
