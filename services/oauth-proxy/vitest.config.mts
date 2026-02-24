import { readFileSync } from 'fs'
import type { Plugin } from 'vite'
import tsconfigPaths from 'vite-tsconfig-paths'
import { defineConfig } from 'vitest/config'

function htmlRawPlugin(): Plugin {
    return {
        name: 'html-raw',
        transform(_code, id) {
            if (id.endsWith('.html')) {
                const content = readFileSync(id, 'utf-8')
                return { code: `export default ${JSON.stringify(content)};`, map: null }
            }
        },
    }
}

export default defineConfig({
    plugins: [tsconfigPaths(), htmlRawPlugin()],
    test: {
        environment: 'node',
    },
})
