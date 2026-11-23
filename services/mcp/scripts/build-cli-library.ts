import { build, type Metafile } from 'esbuild'
import { writeFileSync } from 'node:fs'
import { relative, resolve } from 'node:path'

import { copyInstructions, PROMPTS } from './copy-instructions'
import { cliEsbuildOptions } from './hono-esbuild-config'

// The tool catalog and the skills as ES modules the hog CLI compiles in. Same plugins as the posthog-cli
// bundle. The skills get their own file, so `hog skills read` loads without the tool catalog.
const bundles = [
    { entry: 'src/cli/library.ts', outfile: resolve(process.cwd(), 'dist/cli-library.mjs') },
    { entry: 'src/cli/skills-library.ts', outfile: resolve(process.cwd(), 'dist/cli-skills.mjs') },
]

// copyInstructions() copies tracked prompt files into the gitignored shared/ folder, so esbuild records
// the copies. The metafile names the tracked files instead, because those are what a pull request changes.
const trackedSources = new Map(
    PROMPTS.map(({ src, dest }) => [dest, relative(process.cwd(), resolve(process.cwd(), '../..', src))])
)

function withTrackedSources(metafile: Metafile): Metafile {
    const inputs = Object.entries(metafile.inputs).map(([path, input]) => [trackedSources.get(path) ?? path, input])
    return { ...metafile, inputs: Object.fromEntries(inputs) }
}

copyInstructions()
Promise.all(
    bundles.map(({ entry, outfile }) =>
        build({
            ...cliEsbuildOptions({ outfile, sourcemap: false }),
            entryPoints: [resolve(process.cwd(), entry)],
            // The server's request logs would land on the CLI's stderr. Failures reach the caller as results instead.
            drop: ['console'],
            // The source files each bundle compiles in, which CI reads to tell when hog needs a release.
            metafile: true,
        }).then((result) => {
            writeFileSync(
                outfile.replace(/\.mjs$/, '.metafile.json'),
                JSON.stringify(withTrackedSources(result.metafile))
            )
            console.info(`Built the PostHog CLI library -> ${outfile}`)
        })
    )
).catch((err: unknown) => {
    console.error('Build failed:', err)
    process.exit(1)
})
