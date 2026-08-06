import { build } from 'esbuild'
import { writeFile } from 'node:fs/promises'

import {
    integrationServiceEsbuildOptions,
    integrationServiceMetafile,
    integrationServiceOutfile,
} from './integration-service-esbuild-config'

build(integrationServiceEsbuildOptions())
    .then(async (result) => {
        // The metafile is what check-import-boundary.ts reads, so persist it rather
        // than only holding it in memory for this process.
        await writeFile(integrationServiceMetafile, JSON.stringify(result.metafile))
        console.info(`Built integration-service → ${integrationServiceOutfile}`)
    })
    .catch((err: unknown) => {
        console.error('Build failed:', err)
        process.exit(1)
    })
