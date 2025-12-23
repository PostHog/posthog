import tsconfigPaths from 'vite-tsconfig-paths'
import { defineConfig } from 'vitest/config'

export default defineConfig({
    plugins: [
        tsconfigPaths({ root: '.' }),
        {
            name: 'markdown-loader',
            transform(code, id) {
                if (id.endsWith('.md')) {
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
        testTimeout: 10000,
        setupFiles: ['tests/setup.ts'],
        include: ['tests/**/*.test.ts'],
        exclude: ['node_modules/**', 'dist/**', 'tests/**/*.integration.test.ts'],
    },
})
