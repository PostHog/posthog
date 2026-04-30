import tsconfigPaths from 'vite-tsconfig-paths'
import { defineConfig } from 'vitest/config'

// The Hono and worker entry points import `*.md` and `*.html` template files
// directly. Vitest's default loader rejects those as JS, so we register a tiny
// transform that stringifies their contents. Mirrors the loader in the other
// vitest configs.
const textLoader = {
    name: 'text-loader',
    transform(code: string, id: string) {
        if (id.endsWith('.md') || id.endsWith('.html')) {
            return {
                code: `export default ${JSON.stringify(code)}`,
                map: null,
            }
        }
    },
}

export default defineConfig({
    plugins: [tsconfigPaths({ root: '.' }), textLoader],
    test: {
        globals: true,
        environment: 'node',
        testTimeout: 30000,
        retry: 1, // Retry failed tests once to handle flaky integration tests
        setupFiles: ['tests/setup.ts'],
        include: ['tests/**/*.integration.test.ts'],
        exclude: ['node_modules/**', 'dist/**', 'tests/hono/**'],
        // Run test files sequentially to reduce parallel API load
        fileParallelism: false,
        // Limit concurrent tests within a file
        maxConcurrency: 5,
    },
})
