import { resolve } from 'path'
import { defineConfig } from 'vitest/config'

const frontendDir = resolve(__dirname, '../../frontend')

export default defineConfig({
    resolve: {
        alias: {
            '~': resolve(frontendDir, 'src'),
            lib: resolve(frontendDir, 'src/lib'),
            scenes: resolve(frontendDir, 'src/scenes'),
            queries: resolve(frontendDir, 'src/queries'),
            products: resolve(__dirname, '..'),
            common: resolve(__dirname, '../../common'),
        },
    },
    test: {
        globals: true,
        environment: 'jsdom',
        clearMocks: true,
        include: ['frontend/**/*.{test,spec}.{ts,tsx}'],
        exclude: ['**/node_modules/**'],
        css: false,
    },
})
