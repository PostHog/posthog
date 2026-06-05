import react from '@vitejs/plugin-react'
import { resolve } from 'path'
import { defineConfig } from 'vitest/config'

// Mirror the aliases from vite.ui-apps.config.ts so tests resolve the same
// modules as the production build.
export default defineConfig({
    plugins: [react()],
    resolve: {
        alias: [
            { find: 'products', replacement: resolve(__dirname, '../../products') },
            { find: '@posthog/mcp-ui', replacement: resolve(__dirname, 'src/ui-apps/lib') },
            {
                find: /^@posthog\/quill$/,
                replacement: resolve(__dirname, '../../packages/quill/packages/quill/dist/index.js'),
            },
            {
                find: /^@posthog\/quill-charts$/,
                replacement: resolve(__dirname, '../../packages/quill/packages/charts/src/index.ts'),
            },
            { find: /^lucide-react$/, replacement: resolve(__dirname, 'node_modules/lucide-react') },
            { find: '@common', replacement: resolve(__dirname, '../../common') },
        ],
    },
    test: {
        name: 'ui-apps',
        globals: true,
        environment: 'jsdom',
        setupFiles: ['tests/ui-apps/setup.ts'],
        include: ['tests/ui-apps/**/*.test.tsx'],
    },
})
