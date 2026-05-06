import { build } from 'esbuild'

import { honoEsbuildOptions, honoOutfile } from './hono-esbuild-config'

build(honoEsbuildOptions())
    .then(() => {
        console.info(`Built MCP server → ${honoOutfile}`)
    })
    .catch((err: unknown) => {
        console.error('Build failed:', err)
        process.exit(1)
    })
