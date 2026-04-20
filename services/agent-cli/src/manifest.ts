/**
 * Loads the CLI manifest — a generated JSON file mapping tool names to HTTP
 * details (method, path, params) plus metadata (description, category, scopes).
 *
 * The manifest is produced by `generate-tools.ts` alongside the MCP handlers,
 * so it reflects the same YAML + OpenAPI resolution (skips, overrides, etc.).
 */

import * as fs from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export interface CliParamSchema {
    name: string
    type: string
    required: boolean
    description?: string
}

export interface CliToolManifest {
    method: string
    path: string
    title: string
    description: string
    category: string
    feature: string
    scopes: string[]
    annotations: {
        readOnly: boolean
        destructive: boolean
        idempotent: boolean
    }
    params: {
        path: string[]
        query: string[]
        body: string[]
    }
    soft_delete?: string | boolean
    /** Present for query wrapper tools — the `kind` value injected into the query payload. */
    query_kind?: string
    /** Resolved property schemas for query wrapper tools. */
    query_schema?: CliParamSchema[]
    /** Pre-resolved nested type definitions referenced by query_schema params. */
    types?: Record<string, { properties: CliParamSchema[] }>
}

const MANIFEST_LOCATIONS = [
    // Running from services/agent-cli/src/ (dev with tsx)
    path.resolve(__dirname, '../../mcp/schema/cli-manifest.json'),
    // Running from services/agent-cli/dist/ (built)
    path.resolve(__dirname, '../../../mcp/schema/cli-manifest.json'),
]

export function loadManifest(): Record<string, CliToolManifest> {
    for (const loc of MANIFEST_LOCATIONS) {
        if (fs.existsSync(loc)) {
            return JSON.parse(fs.readFileSync(loc, 'utf-8'))
        }
    }
    throw new Error(
        `CLI manifest not found. Run "hogli build:openapi" to generate it.\nSearched: ${MANIFEST_LOCATIONS.join(', ')}`
    )
}
