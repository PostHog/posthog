#!/usr/bin/env tsx
/**
 * Reads existing services/mcp codegen artifacts and emits three files:
 *   src/generated/client.ts          - runtime Client class, one method per operationId
 *   src/generated/sdk.d.ts           - agent-facing surface: Schemas namespace + Client interface
 *   src/generated/search-index.json  - search docs for operations + types
 */
import * as fs from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'

import { ClientGenerator, type OpenApiSpec, type ToolDefinitionMeta } from './client-generator'
import { loadYamlDefinitions } from './load-yaml'
import { SPECIAL_CLIENT_METHODS } from './special-tools'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const EXEC_ROOT = path.resolve(__dirname, '..')
const MCP_ROOT = path.resolve(EXEC_ROOT, '..')
const REPO_ROOT = path.resolve(MCP_ROOT, '../..')

const OPENAPI_PATH = path.resolve(REPO_ROOT, 'frontend/tmp/openapi.json')
const DEFINITIONS_JSON_PATH = path.resolve(MCP_ROOT, 'schema/generated-tool-definitions.json')
const SCHEMAS_NAMESPACE_PATH = path.resolve(MCP_ROOT, 'src/api/generated.ts')
const DEFINITIONS_YAML_DIR = path.resolve(MCP_ROOT, 'definitions')

const OUT_DIR = path.resolve(EXEC_ROOT, 'src/generated')
const OUT_CLIENT_TS = path.join(OUT_DIR, 'client.ts')
const OUT_SDK_DTS = path.join(OUT_DIR, 'sdk.d.ts')
const OUT_SEARCH_INDEX = path.join(OUT_DIR, 'search-index.json')

function loadOpenApi(): OpenApiSpec {
    if (!fs.existsSync(OPENAPI_PATH)) {
        console.error(`OpenAPI schema not found at ${OPENAPI_PATH}.`)
        console.error(`Run \`hogli build:openapi\` from the repo root first.`)
        process.exit(1)
    }
    return JSON.parse(fs.readFileSync(OPENAPI_PATH, 'utf-8')) as OpenApiSpec
}

function loadDefinitions(): Record<string, ToolDefinitionMeta> {
    if (!fs.existsSync(DEFINITIONS_JSON_PATH)) {
        console.warn(`Tool definitions not found at ${DEFINITIONS_JSON_PATH}; descriptions will be sparse.`)
        return {}
    }
    return JSON.parse(fs.readFileSync(DEFINITIONS_JSON_PATH, 'utf-8')) as Record<string, ToolDefinitionMeta>
}

function loadSchemasNamespaceSource(): string {
    if (!fs.existsSync(SCHEMAS_NAMESPACE_PATH)) {
        console.error(`Schemas namespace not found at ${SCHEMAS_NAMESPACE_PATH}.`)
        console.error(`Run \`pnpm --filter @posthog/mcp generate-mcp-types\` first.`)
        process.exit(1)
    }
    return fs.readFileSync(SCHEMAS_NAMESPACE_PATH, 'utf-8')
}

/**
 * Extract the actual exported names from the Schemas namespace source.
 * Orval normalizes some OpenAPI schema names (e.g. `DAG` → `Dag`,
 * `PatchedIntegration` → `PatchedIntegrationConfig`), so we can't rely on the
 * raw OpenAPI names. If a $ref points to a name that doesn't exist in the
 * actual namespace, the generator emits `unknown` instead of a broken `Schemas.X`.
 */
function knownSchemasFromNamespace(source: string): Set<string> {
    const names = new Set<string>()
    const re = /export\s+(?:type|interface|const)\s+([A-Z][A-Za-z0-9_]*)/g
    let match: RegExpExecArray | null
    while ((match = re.exec(source)) !== null) {
        names.add(match[1]!)
    }
    return names
}

function ensureDir(dir: string): void {
    fs.mkdirSync(dir, { recursive: true })
}

function main(): void {
    const spec = loadOpenApi()
    const definitions = loadDefinitions()
    const schemasNamespaceSource = loadSchemasNamespaceSource()
    const knownSchemas = knownSchemasFromNamespace(schemasNamespaceSource)
    const yamlIndex = loadYamlDefinitions(DEFINITIONS_YAML_DIR)

    const generator = new ClientGenerator(spec, definitions, knownSchemas, {
        yamlIndex,
        specialMethods: SPECIAL_CLIENT_METHODS,
    })
    const ops = generator.collectOperations()

    const clientTs = generator.renderClientTs(ops)
    const sdkDts = generator.renderSdkDts(ops, schemasNamespaceSource)
    const searchDocs = generator.buildSearchDocs(ops, schemasNamespaceSource)

    ensureDir(OUT_DIR)
    fs.writeFileSync(OUT_CLIENT_TS, clientTs)
    fs.writeFileSync(OUT_SDK_DTS, sdkDts)
    fs.writeFileSync(OUT_SEARCH_INDEX, JSON.stringify(searchDocs, null, 2))
}

main()
