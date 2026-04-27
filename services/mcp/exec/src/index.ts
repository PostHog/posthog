#!/usr/bin/env node
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'

import { Client } from './generated/client'
import { Context } from './lib/context'
import { HttpClient } from './lib/http-client'
import type { SearchDoc } from './lib/searcher'
import { ExecMcpServer } from './server'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

interface Env {
    apiKey: string
    baseUrl: string
}

function readEnv(): Env {
    const apiKey = process.env.POSTHOG_API_KEY
    const baseUrl = process.env.POSTHOG_BASE_URL ?? 'https://us.posthog.com'
    if (!apiKey) {
        process.stderr.write('POSTHOG_API_KEY is required.\n')
        process.exit(1)
    }
    return { apiKey, baseUrl }
}

function loadGeneratedAssets(): { sdkDtsSource: string; searchDocs: SearchDoc[] } {
    // When run via tsx (dev): __dirname is .../src; generated/ is sibling.
    // When run from dist/: __dirname is .../dist; generated assets sit alongside.
    const candidates = [path.resolve(__dirname, 'generated'), path.resolve(__dirname, '../src/generated')]
    const generatedDir = candidates.find((dir) => fs.existsSync(path.join(dir, 'sdk.d.ts')))
    if (!generatedDir) {
        process.stderr.write('Generated assets not found. Run `pnpm --filter @posthog/mcp-exec generate` first.\n')
        process.exit(1)
    }
    const sdkDtsSource = fs.readFileSync(path.join(generatedDir, 'sdk.d.ts'), 'utf-8')
    const searchDocs = JSON.parse(fs.readFileSync(path.join(generatedDir, 'search-index.json'), 'utf-8')) as SearchDoc[]
    return { sdkDtsSource, searchDocs }
}

async function main(): Promise<void> {
    const env = readEnv()
    const { sdkDtsSource, searchDocs } = loadGeneratedAssets()

    const http = new HttpClient({ baseUrl: env.baseUrl, apiKey: env.apiKey })
    const context = new Context(http)
    const client = new Client(http, context)

    const server = new ExecMcpServer({
        sdkDtsSource,
        searchDocs,
        clientFactory: () => client,
    })

    const transport = new StdioServerTransport()
    await server.server.connect(transport)
}

main().catch((err) => {
    process.stderr.write(`fatal: ${err?.stack ?? err}\n`)
    process.exit(1)
})
