import { readFileSync } from 'fs'
import type { Plugin } from 'vite'
import tsconfigPaths from 'vite-tsconfig-paths'
import { defineConfig } from 'vitest/config'

// Mirrors the Data rule in wrangler.jsonc, so tests see the same ArrayBuffer the Worker gets.
function binaryRawPlugin(): Plugin {
    return {
        name: 'binary-raw',
        transform(_code, id) {
            if (id.endsWith('.woff2')) {
                const base64 = readFileSync(id).toString('base64')
                return {
                    code: `const bytes = Buffer.from(${JSON.stringify(base64)}, 'base64');
export default bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);`,
                    map: null,
                }
            }
        },
    }
}

// Mirrors the Text rule in wrangler.jsonc.
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
    plugins: [tsconfigPaths(), htmlRawPlugin(), binaryRawPlugin()],
    test: {
        environment: 'node',
    },
})
