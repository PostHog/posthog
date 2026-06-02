import { build } from 'esbuild'

import { cliEsbuildOptions, cliOutfile } from './hono-esbuild-config'

build(cliEsbuildOptions())
    .then(() => {
        console.info(`Built PostHog API CLI -> ${cliOutfile}`)
    })
    .catch((err: unknown) => {
        console.error('Build failed:', err)
        process.exit(1)
    })
