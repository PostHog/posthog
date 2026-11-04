import assert from 'node:assert/strict'
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import vm from 'node:vm'
import { build } from 'esbuild'

import { mobileReplayDependencies } from './replay-player-dependencies.mjs'

test('bundles mobile browser exports even when shared sources have conflicting dependencies', async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), 'mobile-replay-dependencies-'))
    try {
        const mobile = path.join(root, 'mobile')
        const shared = path.join(root, 'common')
        for (const [directory, label] of [
            [mobile, 'mobile'],
            [shared, 'shared'],
        ]) {
            const dependency = path.join(directory, 'node_modules/posthog-js')
            await mkdir(dependency, { recursive: true })
            await writeFile(
                path.join(dependency, 'package.json'),
                JSON.stringify({
                    name: 'posthog-js',
                    exports: { './rrweb': { browser: './browser.js', default: './default.js' } },
                })
            )
            await writeFile(path.join(dependency, 'browser.js'), `export default '${label}-browser'`)
            await writeFile(path.join(dependency, 'default.js'), `export default '${label}-default'`)
        }
        const entry = path.join(shared, 'entry.js')
        await writeFile(entry, "import value from 'posthog-js/rrweb'; globalThis.selected = value")
        const options = {
            entryPoints: [entry],
            bundle: true,
            write: false,
            nodePaths: [path.join(mobile, 'node_modules')],
        }
        const run = async (plugins = []) => {
            const result = await build({ ...options, plugins })
            const context = {}
            vm.runInNewContext(result.outputFiles[0].text, context)
            return context.selected
        }
        assert.equal(await run(), 'shared-browser')
        assert.equal(await run([mobileReplayDependencies(mobile)]), 'mobile-browser')
        await rm(path.join(shared, 'node_modules'), { recursive: true })
        assert.equal(await run([mobileReplayDependencies(mobile)]), 'mobile-browser')
    } finally {
        await rm(root, { recursive: true, force: true })
    }
})
