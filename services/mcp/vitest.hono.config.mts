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
        testTimeout: 15000,
        setupFiles: ['tests/hono/setup.ts'],
        include: ['tests/hono/**/*.test.ts'],
        exclude: ['node_modules/**', 'dist/**'],
    },
})
