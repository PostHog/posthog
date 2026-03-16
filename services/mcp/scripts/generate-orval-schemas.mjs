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
import { execSync, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse as parseYaml } from 'yaml'

import { applyNestedExclusions, filterSchemaByOperationIds } from '@posthog/openapi-codegen'

import { discoverDefinitions, resolveSchemaPath } from './lib/definitions.mjs'
import { stripEnumMinLength } from './lib/schema-transforms.mjs'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const mcpRoot = path.resolve(__dirname, '..')
const repoRoot = path.resolve(mcpRoot, '../..')
const productsDir = path.resolve(repoRoot, 'products')
const generatedRoot = path.resolve(mcpRoot, 'src', 'generated')
const definitionsDir = path.resolve(mcpRoot, 'definitions')

const schemaPath = resolveSchemaPath(repoRoot)

if (!fs.existsSync(schemaPath)) {
    console.error(`OpenAPI schema not found at ${schemaPath}. Run \`hogli build:openapi-schema\` first.`)
    process.exit(1)
}

/**
 * Parse a YAML tool definition and return operationIds plus all exclude_params
 * grouped by operationId for schema-level exclusion before Orval runs.
 */
function parseToolDefinition(filePath) {
    const content = fs.readFileSync(filePath, 'utf-8')
    const parsed = parseYaml(content)
    const operationIds = new Set()
    /** @type {Map<string, string[]>} */
    const schemaExclusions = new Map()

    if (parsed?.tools) {
        for (const tool of Object.values(parsed.tools)) {
            if (!tool?.enabled || !tool?.operation) {
                continue
            }

            operationIds.add(tool.operation)
            const excludeParams = tool.exclude_params ?? []
            if (excludeParams.length > 0) {
                schemaExclusions.set(tool.operation, excludeParams)
            }
        }
    }
    return { operationIds, schemaExclusions }
}

// ------------------------------------------------------------------
// OpenAPI post-processing (MCP-specific)
// ------------------------------------------------------------------

/**
 * Strip 'default: null' from nullable properties in OpenAPI schemas.
 *
 * Orval generates invalid Zod like `.string().default(null)` when it sees
 * `nullable: true` with `default: null`. Removing the null default causes
 * Orval to correctly generate `.nullable()` instead.
 */
function stripNullDefaults(obj) {
    if (!obj || typeof obj !== 'object') {
        return obj
    }
    if (Array.isArray(obj)) {
        return obj.map(stripNullDefaults)
    }
    const result = {}
    for (const [key, value] of Object.entries(obj)) {
        // Skip 'default' key if value is null and sibling 'nullable' is true
        if (key === 'default' && value === null && obj.nullable === true) {
            continue
        }
        result[key] = stripNullDefaults(value)
    }
    return result
}

/**
 * Remove readOnly properties from `required` arrays in the schema.
 *
 * drf-spectacular includes readOnly fields in `required` because they're
 * always present in responses. But Orval generates a single Zod schema
 * used for request validation, where readOnly fields shouldn't be required.
 * This strips them so MCP tool callers don't need to provide server-computed
 * fields like `bytecode`, `order`, or `transpiled`.
 */
function stripReadOnlyFromRequired(obj) {
    if (!obj || typeof obj !== 'object') {
        return
    }
    if (Array.isArray(obj)) {
        for (const item of obj) {
            stripReadOnlyFromRequired(item)
        }
        return
    }
    if (obj.properties && Array.isArray(obj.required)) {
        obj.required = obj.required.filter((fieldName) => {
            const prop = obj.properties[fieldName]
            return !prop || !prop.readOnly
        })
        if (obj.required.length === 0) {
            delete obj.required
        }
    }
    for (const value of Object.values(obj)) {
        stripReadOnlyFromRequired(value)
    }
}

/**
 * Strip `format: "uuid"` from all string properties in the schema.
 * Zod 4's `.uuid()` enforces strict RFC 4122 version/variant bits,
 * which some PostHog UUID generation paths don't satisfy.
 * Since these are API response schemas, there's no value in
 * re-validating the UUID format client-side.
 */
function stripUuidFormat(obj) {
    if (!obj || typeof obj !== 'object') {
        return
    }
    if (obj.type === 'string' && obj.format === 'uuid') {
        delete obj.format
    }
    for (const value of Object.values(obj)) {
        stripUuidFormat(value)
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

    // Annotate top-level exported Zod expressions with @__PURE__ so esbuild
    // can tree-shake unused schemas out of the bundle.
    const generated = fs.readFileSync(outputFile, 'utf-8')
    const annotated = generated.replace(/^(export const \w+ =) (zod\.)/gm, '$1 /* @__PURE__ */ $2')
    fs.writeFileSync(outputFile, annotated)

    return moduleOutputDir
}

// ------------------------------------------------------------------
// Main
// ------------------------------------------------------------------

const definitions = discoverDefinitions({ definitionsDir, productsDir })

if (definitions.length === 0) {
    console.log('No MCP YAML definitions found, skipping Orval Zod generation.')
    process.exit(0)
}

const fullSchema = JSON.parse(fs.readFileSync(schemaPath, 'utf-8'))
const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mcp-orval-'))
const outputDirs = []
let totalEnabledOps = 0

for (const def of definitions) {
    const { operationIds, schemaExclusions } = parseToolDefinition(def.filePath)
    if (operationIds.size === 0) {
        continue
    }
    totalEnabledOps += operationIds.size

    let filtered = filterSchemaByOperationIds(fullSchema, operationIds, { includeResponseSchemas: false })

    // Annotate title for easier debugging
    filtered.info.title = `${fullSchema.info?.title ?? 'API'} - MCP ${operationIds.size} enabled ops`

    filtered = stripNullDefaults(filtered)
    stripUuidFormat(filtered)
    stripReadOnlyFromRequired(filtered)
    applyNestedExclusions(filtered, schemaExclusions)
    stripEnumMinLength(filtered)
    const pathCount = Object.keys(filtered.paths).length
    const schemaCount = Object.keys(filtered.components.schemas).length

    try {
        const outDir = runOrval(def.moduleName, filtered, tmpDir)
        console.log(
            `   ✓ ${def.moduleName}: ${pathCount} paths, ${schemaCount} schemas (${operationIds.size} enabled ops)`
        )
        outputDirs.push(outDir)
    } catch (err) {
        console.error(`   ✗ ${def.moduleName}: Orval failed — ${err.message}`)
        process.exit(1)
    }
}

fs.rmSync(tmpDir, { recursive: true, force: true })
console.log(`MCP Orval: ${outputDirs.length} module(s), ${totalEnabledOps} enabled operations total`)

if (outputDirs.length > 0) {
    const generatedFiles = outputDirs.map((d) => path.join(d, 'api.ts'))
    spawnSync(path.join(repoRoot, 'bin/hogli'), ['format:js', ...generatedFiles], { stdio: 'pipe', cwd: repoRoot })
}
