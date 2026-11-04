import { readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'

import { mobileReplayDependencies } from './replay-player-dependencies.mjs'

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const output = path.join(app, 'src/features/replay/player/player.bundle.json')
const result = await build({
    entryPoints: [path.join(app, 'src/features/replay/player/player.browser.js')],
    bundle: true,
    write: false,
    format: 'iife',
    platform: 'browser',
    target: 'es2020',
    minify: true,
    legalComments: 'inline',
    nodePaths: [path.join(app, 'node_modules')],
    plugins: [mobileReplayDependencies(app)],
    alias: { '@posthog/replay-shared': path.resolve(app, '../../common/replay-shared/src/index.ts') },
    define: { 'process.env.NODE_ENV': '"production"', 'process.env.LANG': '""', 'process.env': '{}' },
})
const content = `${JSON.stringify(result.outputFiles[0].text)}\n`
if (process.argv.includes('--check')) {
    if ((await readFile(output, 'utf8')) !== content) {
        throw new Error('Replay player bundle is stale. Run node scripts/build-replay-player.mjs.')
    }
} else {
    await writeFile(output, content)
}
