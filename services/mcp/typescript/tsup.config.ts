import { defineConfig } from 'tsup'

// NPM package build (default)
const packageConfig = defineConfig({
    entry: {
        index: 'src/index.ts',
        tools: 'src/tools/index.ts',
        'ai-sdk': 'src/integrations/ai-sdk/index.ts',
        langchain: 'src/integrations/langchain/index.ts',
    },
    format: ['cjs', 'esm'],
    dts: true,
    clean: true,
    splitting: false,
    treeshake: true,
    esbuildOptions(options) {
        options.loader = {
            ...options.loader,
            '.md': 'text',
        }
    },
})

// Server build (Node.js)
const serverConfig = defineConfig({
    entry: {
        index: 'src/server/index.ts',
    },
    outDir: 'dist/server',
    format: ['cjs'],
    dts: false,
    clean: true,
    splitting: false,
    treeshake: true,
    platform: 'node',
    target: 'node22',
    esbuildOptions(options) {
        options.loader = {
            ...options.loader,
            '.md': 'text',
        }
    },
})

export default process.env.BUILD_SERVER === 'true' ? serverConfig : packageConfig
