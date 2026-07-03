#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { postSection } from '../../../frontend/bin/ci-report/update-ci-report.mjs'

const distDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'public', 'ui-apps')

// App dirs are the ones containing main.js; wrapper dirs (e.g. generated/) recurse.
function collectApps(dir) {
    const apps = []
    for (const entry of fs.readdirSync(dir).sort()) {
        const full = path.join(dir, entry)
        if (!fs.statSync(full).isDirectory()) {
            continue
        }
        const jsPath = path.join(full, 'main.js')
        if (fs.existsSync(jsPath)) {
            const cssPath = path.join(full, 'styles.css')
            apps.push({
                app: entry,
                jsKb: fs.statSync(jsPath).size / 1024,
                cssKb: fs.existsSync(cssPath) ? fs.statSync(cssPath).size / 1024 : null,
            })
        } else {
            apps.push(...collectApps(full))
        }
    }
    return apps
}

const apps = fs.existsSync(distDir) ? collectApps(distDir) : []
if (!apps.length) {
    console.info('No built UI apps found — nothing to post.')
    process.exit(0)
}

const totalJsKb = apps.reduce((total, { jsKb }) => total + jsKb, 0)
const body = [
    'Built size of each MCP UI app (`main.js` + `styles.css`).',
    '',
    '| App | JS | CSS |',
    '| --- | --- | --- |',
    ...apps.map(
        ({ app, jsKb, cssKb }) =>
            `| ${app} | ${jsKb.toFixed(1)} KB | ${cssKb === null ? '—' : `${cssKb.toFixed(1)} KB`} |`
    ),
].join('\n')

await postSection({
    id: 'mcp-ui-apps',
    status: 'info',
    summary: `${apps.length} app(s), ${totalJsKb.toFixed(1)} KB JS`,
    body,
})
