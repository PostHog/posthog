#!/usr/bin/env node
import * as path from 'path'
import { fileURLToPath } from 'url'

import {
    buildInParallel,
    copyIndexHtml,
    // copyPublicFolder,
    createHashlessEntrypoints,
    gatherProductManifests,
    isDev,
    startDevServer,
} from './utils.mjs'

export const __dirname = path.dirname(fileURLToPath(import.meta.url))

startDevServer(__dirname)
// copyPublicFolder(path.resolve(__dirname, 'public'), path.resolve(__dirname, 'dist'))
// writeIndexHtml()
// writeExporterHtml()
// gatherProductManifests()

await buildInParallel(
    [
        {
            name: 'LLM Observability',
            globalName: 'posthogApp',
            entryPoints: ['frontend/LLMObservabilityScene.tsx'],
            splitting: false,
            format: 'esm',
            minify: false,
            // outdir: path.resolve(__dirname, 'dist'),
            outfile: path.resolve(__dirname, 'dist', 'llm_observability.js'),
            absWorkingDir: __dirname,
            bundle: true,
            external: ["lib", "scenes", "@posthog/lemon-ui", "~", "products", "@posthog/icons", "kea", "kea-loaders", "kea-forms", "kea-router", "react"]
        },
    ],
    {
        async onBuildComplete(config, buildResponse) {
            if (!buildResponse) {
                return
            }

            const { chunks, entrypoints } = buildResponse

            // if (config.name === 'PostHog App') {
            //     if (Object.keys(chunks).length === 0) {
            //         throw new Error('Could not get chunk metadata for bundle "PostHog App."')
            //     }
            //     if (!isDev && Object.keys(entrypoints).length === 0) {
            //         throw new Error('Could not get entrypoint for bundle "PostHog App."')
            //     }
            //     writeIndexHtml(chunks, entrypoints)
            // }

            // if (config.name === 'Exporter') {
            //     writeExporterHtml(chunks, entrypoints)
            // }

            createHashlessEntrypoints(__dirname, entrypoints)
        },
    }
)

// export function writeIndexHtml(chunks = {}, entrypoints = []) {
//     copyIndexHtml(__dirname, 'src/index.html', 'dist/index.html', 'index', chunks, entrypoints)
//     copyIndexHtml(__dirname, 'src/layout.html', 'dist/layout.html', 'index', chunks, entrypoints)
// }

// export function writeExporterHtml(chunks = {}, entrypoints = []) {
//     copyIndexHtml(__dirname, 'src/exporter/index.html', 'dist/exporter.html', 'exporter', chunks, entrypoints)
// }
