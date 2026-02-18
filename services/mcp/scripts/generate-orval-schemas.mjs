#!/usr/bin/env node
/**
 * Generates Orval Zod schemas for MCP tool handlers.
 *
 * Discovers MCP YAML definitions (services/mcp/definitions/ and
 * products/{name}/mcp/), extracts referenced operationIds, filters
 * the OpenAPI schema per definition, and runs Orval with `client: 'zod'`.
 *
 * Output: services/mcp/src/generated/{moduleName}/api.ts per definition
 *
 * Invoked by `hogli build:openapi` as a separate step from frontend types.
 */
/* eslint-disable no-console */
import { execSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const mcpRoot = path.resolve(__dirname, '..')
const repoRoot = path.resolve(mcpRoot, '../..')
const productsDir = path.resolve(repoRoot, 'products')
const generatedRoot = path.resolve(mcpRoot, 'src', 'generated')
const definitionsDir = path.resolve(mcpRoot, 'definitions')

const defaultSchemaPath = path.resolve(repoRoot, 'frontend', 'tmp', 'openapi.json')
const schemaPath = process.env.OPENAPI_SCHEMA_PATH
    ? path.resolve(repoRoot, process.env.OPENAPI_SCHEMA_PATH)
    : defaultSchemaPath

if (!fs.existsSync(schemaPath)) {
    console.error(`OpenAPI schema not found at ${schemaPath}. Run \`hogli build:openapi-schema\` first.`)
    process.exit(1)
}

// ------------------------------------------------------------------
// Definition discovery — mirrors generate-tools.ts discoverDefinitions()
// ------------------------------------------------------------------

function discoverDefinitions() {
    const sources = []

    if (fs.existsSync(definitionsDir)) {
        for (const file of fs.readdirSync(definitionsDir)) {
            if (!file.endsWith('.yaml') && !file.endsWith('.yml')) {
                continue
            }
            sources.push({
                moduleName: file.replace(/\.ya?ml$/, ''),
                filePath: path.join(definitionsDir, file),
            })
        }
    }

    if (fs.existsSync(productsDir)) {
        for (const product of fs.readdirSync(productsDir, { withFileTypes: true })) {
            if (!product.isDirectory() || product.name.startsWith('_')) {
                continue
            }
            const mcpDir = path.join(productsDir, product.name, 'mcp')
            if (!fs.existsSync(mcpDir)) {
                continue
            }
            for (const file of fs.readdirSync(mcpDir)) {
                if (!file.endsWith('.yaml') && !file.endsWith('.yml')) {
                    continue
                }
                const moduleName =
                    file === 'tools.yaml' || file === 'tools.yml' ? product.name : file.replace(/\.ya?ml$/, '')
                sources.push({
                    moduleName,
                    filePath: path.join(mcpDir, file),
                })
            }
        }
    }

    return sources
}

function collectOperationIdsFromFile(filePath) {
    const operationIds = new Set()
    const content = fs.readFileSync(filePath, 'utf-8')
    for (const match of content.matchAll(/^\s+operation:\s+(\S+)/gm)) {
        operationIds.add(match[1])
    }
    return operationIds
}

// ------------------------------------------------------------------
// OpenAPI filtering
// ------------------------------------------------------------------

function collectSchemaRefs(obj, refs = new Set()) {
    if (!obj || typeof obj !== 'object') {
        return refs
    }
    if (obj.$ref && typeof obj.$ref === 'string') {
        refs.add(obj.$ref)
    }
    for (const value of Object.values(obj)) {
        collectSchemaRefs(value, refs)
    }
    return refs
}

function resolveNestedRefs(schemas, refs) {
    const allRefs = new Set(refs)
    let changed = true
    while (changed) {
        changed = false
        for (const ref of allRefs) {
            const schemaName = ref.replace('#/components/schemas/', '')
            const schema = schemas[schemaName]
            if (schema) {
                for (const nestedRef of collectSchemaRefs(schema)) {
                    if (!allRefs.has(nestedRef)) {
                        allRefs.add(nestedRef)
                        changed = true
                    }
                }
            }
        }
    }
    return allRefs
}

function filterSchemaByOperationIds(fullSchema, operationIds) {
    const httpMethods = new Set(['get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace'])
    const filteredPaths = {}
    const refs = new Set()

    for (const [pathKey, operations] of Object.entries(fullSchema.paths ?? {})) {
        for (const [method, operation] of Object.entries(operations ?? {})) {
            if (!httpMethods.has(method)) {
                continue
            }
            if (!operationIds.has(operation.operationId)) {
                continue
            }
            filteredPaths[pathKey] ??= {}
            filteredPaths[pathKey][method] = operation
            collectSchemaRefs(operation, refs)
        }
    }

    const allSchemas = fullSchema.components?.schemas ?? {}
    const allRefs = resolveNestedRefs(allSchemas, refs)
    const filteredSchemas = {}

    for (const ref of allRefs) {
        const schemaName = ref.replace('#/components/schemas/', '')
        if (allSchemas[schemaName]) {
            filteredSchemas[schemaName] = allSchemas[schemaName]
        }
    }

    return {
        openapi: fullSchema.openapi,
        info: { ...fullSchema.info, title: `${fullSchema.info?.title ?? 'API'} - MCP ${operationIds.size} ops` },
        paths: filteredPaths,
        components: { schemas: filteredSchemas },
    }
}

// ------------------------------------------------------------------
// Orval runner
// ------------------------------------------------------------------

function runOrval(moduleName, filteredSchema, tmpDir) {
    const moduleOutputDir = path.join(generatedRoot, moduleName)
    const tempFile = path.join(tmpDir, `${moduleName}.json`)
    const configFile = path.join(tmpDir, `orval-${moduleName}.config.mjs`)
    const outputFile = path.join(moduleOutputDir, 'api.ts')

    fs.writeFileSync(tempFile, JSON.stringify(filteredSchema, null, 2))
    fs.mkdirSync(moduleOutputDir, { recursive: true })

    const config = `
import { defineConfig } from 'orval';
export default defineConfig({
  api: {
    input: '${tempFile}',
    output: {
      target: '${outputFile}',
      mode: 'split',
      client: 'zod',
      prettier: false,
      override: {
        header: (info) => [
          'Auto-generated from the Django backend OpenAPI schema.',
          'MCP service uses these Zod schemas for generated tool handlers.',
          'To regenerate: hogli build:openapi',
          '',
          ...(info?.title ? [info.title] : []),
          ...(info?.version ? ['OpenAPI spec version: ' + info.version] : []),
        ],
        components: {
          schemas: { suffix: 'Api' },
        },
      },
    },
  },
});
`
    fs.writeFileSync(configFile, config)
    execSync(`pnpm exec orval --config "${configFile}"`, { stdio: 'pipe', cwd: repoRoot })
    return moduleOutputDir
}

// ------------------------------------------------------------------
// Main
// ------------------------------------------------------------------

const definitions = discoverDefinitions()

if (definitions.length === 0) {
    console.log('No MCP YAML definitions found, skipping Orval Zod generation.')
    process.exit(0)
}

const fullSchema = JSON.parse(fs.readFileSync(schemaPath, 'utf-8'))
const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mcp-orval-'))
const outputDirs = []
let totalOps = 0

for (const def of definitions) {
    const operationIds = collectOperationIdsFromFile(def.filePath)
    if (operationIds.size === 0) {
        continue
    }
    totalOps += operationIds.size

    const filtered = filterSchemaByOperationIds(fullSchema, operationIds)
    const pathCount = Object.keys(filtered.paths).length
    const schemaCount = Object.keys(filtered.components.schemas).length

    try {
        const outDir = runOrval(def.moduleName, filtered, tmpDir)
        console.log(`   ✓ ${def.moduleName}: ${pathCount} paths, ${schemaCount} schemas (${operationIds.size} ops)`)
        outputDirs.push(outDir)
    } catch (err) {
        console.error(`   ✗ ${def.moduleName}: Orval failed — ${err.message}`)
        process.exit(1)
    }
}

// Format all generated files
if (outputDirs.length > 0) {
    const globs = outputDirs.map((d) => `"${d}/**/*.ts"`).join(' ')
    try {
        execSync(`pnpm exec prettier --write ${globs}`, { stdio: 'pipe', cwd: repoRoot })
    } catch {
        // Not critical
    }
}

fs.rmSync(tmpDir, { recursive: true, force: true })
console.log(`MCP Orval: ${outputDirs.length} module(s), ${totalOps} operations total`)
