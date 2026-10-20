import tsconfigPaths from 'vite-tsconfig-paths'
import { defineConfig } from 'vitest/config'

// Tests that download real upstream artifacts. They stay out of the unit and integration
// configs so a slow or broken third party cannot fail a required check; the scheduled
// ci-mcp-live-canary.yml workflow runs them instead.
export default defineConfig({
    plugins: [tsconfigPaths({ root: '.' })],
    test: {
        globals: true,
        environment: 'node',
        testTimeout: 30000,
        retry: 1,
        include: ['tests/live/**/*.live.test.ts'],
    },
})
