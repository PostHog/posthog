import tsconfigPaths from 'vite-tsconfig-paths'
import { defineConfig } from 'vitest/config'

export default defineConfig({
    plugins: [
        tsconfigPaths({ root: '.' }),
        {
            name: 'text-loader',
            transform(code, id) {
                if (id.endsWith('.md') || id.endsWith('.html')) {
                    return {
                        code: `export default ${JSON.stringify(code)}`,
                        map: null,
                    }
                }
            },
        },
    ],
    test: {
        globals: true,
        environment: 'node',
        testTimeout: 60000,
        retry: 1,
        setupFiles: ['tests/hono/setup.ts'],
        include: ['tests/hono/**/*.integration.test.ts'],
        exclude: ['node_modules/**', 'dist/**'],
        fileParallelism: false,
        maxConcurrency: 3,
    },
})
