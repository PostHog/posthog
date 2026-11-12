import { build } from 'esbuild'
import { resolve } from 'node:path'

import { copyInstructions } from './copy-instructions'
import { cliEsbuildOptions } from './hono-esbuild-config'

// The tool catalog and the skills as ES modules the hog CLI compiles in. Same plugins as the posthog-cli
// bundle. The skills get their own file, so `hog skills read` loads without the tool catalog.
const bundles = [
    { entry: 'src/cli/library.ts', outfile: resolve(process.cwd(), 'dist/cli-library.mjs') },
    { entry: 'src/cli/skills-library.ts', outfile: resolve(process.cwd(), 'dist/cli-skills.mjs') },
]

copyInstructions()
Promise.all(
    bundles.map(({ entry, outfile }) =>
        build({
            ...cliEsbuildOptions({ outfile, sourcemap: false }),
            entryPoints: [resolve(process.cwd(), entry)],
            // The server's request logs would land on the CLI's stderr. Failures reach the caller as results instead.
            drop: ['console'],
        }).then(() => console.info(`Built the PostHog CLI library -> ${outfile}`))
    )
).catch((err: unknown) => {
    console.error('Build failed:', err)
    process.exit(1)
})
