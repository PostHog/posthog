import { defineConfig } from 'tsup'

export default defineConfig({
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
