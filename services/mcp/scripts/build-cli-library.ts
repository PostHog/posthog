import { build } from 'esbuild'
import { resolve } from 'node:path'

import { copyInstructions } from './copy-instructions'
import { cliEsbuildOptions } from './hono-esbuild-config'

// The tool catalog as an ES module the hog CLI compiles in. Same plugins as the posthog-cli bundle.
const outfile = resolve(process.cwd(), 'dist/cli-library.mjs')

copyInstructions()
build({
    ...cliEsbuildOptions({ outfile, sourcemap: false }),
    entryPoints: [resolve(process.cwd(), 'src/cli/library.ts')],
    // The server's request logs would land on the CLI's stderr. Failures reach the caller as results instead.
    drop: ['console'],
})
    .then(() => {
        console.info(`Built the PostHog CLI tool library -> ${outfile}`)
    })
    .catch((err: unknown) => {
        console.error('Build failed:', err)
        process.exit(1)
    })
