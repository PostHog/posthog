import { build } from 'esbuild'

import { copyInstructions } from './copy-instructions'
import { cliEsbuildOptions, cliOutfile } from './hono-esbuild-config'

// Populate the gitignored `shared/` tree (playbooks + guidelines) so esbuild
// can inline it via `@shared/*`. Mirrors build-hono.ts.
copyInstructions()

build(cliEsbuildOptions())
    .then(() => {
        console.info(`Built PostHog API CLI -> ${cliOutfile}`)
    })
    .catch((err: unknown) => {
        console.error('Build failed:', err)
        process.exit(1)
    })
