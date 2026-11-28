#!/usr/bin/env node
import { build } from 'esbuild'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { pathToFileURL } from 'node:url'
import { parse } from 'yaml'

import { cliEsbuildOptions } from './hono-esbuild-config.ts'
import { discoverDefinitions, resolveSchemaPath } from './lib/definitions.mjs'
import { emitSdk } from './lib/sdk-emitter.mjs'
import { readHandlerResultTypes } from './lib/sdk-handler-types.mjs'
import { sharedResultType } from './lib/sdk-output-adapters.mjs'
import { annotateDocumentation } from './lib/sdk-schema.mjs'
import { camelCase, resolveSharedOperation } from './lib/sdk-shared-operation.mjs'
import { CategoryConfigSchema, QueryWrappersConfigSchema } from './yaml-config-schema.ts'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')

export async function generateSdk({
    repoRoot = root,
    schemaPath = resolveSchemaPath(repoRoot),
    outputDir = path.join(repoRoot, 'packages/sdk'),
    dryRun = false,
} = {}) {
    const schema = JSON.parse(await fs.readFile(schemaPath, 'utf8'))
    const querySchema = JSON.parse(await fs.readFile(path.join(repoRoot, 'frontend/src/queries/schema.json'), 'utf8'))
    annotateDocumentation(schema, { kind: 'openapi', file: 'openapi.json' })
    annotateDocumentation(querySchema, { kind: 'query_schema', file: 'frontend/src/queries/schema.json' })
    const sources = discoverDefinitions({
        definitionsDir: path.join(repoRoot, 'services/mcp/definitions'),
        productsDir: path.join(repoRoot, 'products'),
    })
    const definitions = new Map()
    for (const source of sources) {
        const parsed = parse(await fs.readFile(source.filePath, 'utf8'))
        const category = ('tools' in parsed ? CategoryConfigSchema : QueryWrappersConfigSchema).parse(parsed)
        for (const [name, config] of Object.entries({ ...category.tools, ...category.wrappers })) {
            if (!config.enabled) {
                continue
            }
            const entry = { ...source, name, config, category, file: path.relative(repoRoot, source.filePath) }
            if (config.confirmed_action) {
                definitions.set(`${name}-prepare`, entry)
                definitions.set(`${name}-execute`, entry)
            } else {
                definitions.set(name, entry)
            }
        }
    }
    const operations = []
    const coverage = []
    const methodNames = new Set()
    // A failed generation must not leave a partly refreshed public contract.
    const staging = await fs.mkdtemp(path.join(path.dirname(outputDir), '.sdk-generated-'))
    try {
        const mcpDir = path.join(repoRoot, 'services/mcp')
        const require = createRequire(path.join(mcpDir, 'package.json'))
        execFileSync(process.execPath, ['--import', require.resolve('tsx'), 'scripts/copy-instructions.ts'], {
            cwd: mcpDir,
        })
        const bundle = path.join(staging, 'schemas.mjs')
        await build({
            ...cliEsbuildOptions({ outfile: bundle, sourcemap: false }),
            absWorkingDir: path.join(repoRoot, 'services/mcp'),
            entryPoints: ['scripts/lib/sdk-tool-schemas.ts'],
            tsconfig: 'tsconfig.json',
        })
        const { getSdkSchemas } = await import(pathToFileURL(bundle).href)
        const { inputs, catalog } = getSdkSchemas()
        const expected = Object.keys(catalog).sort()
        const registered = Object.keys(inputs).sort()
        if (JSON.stringify(expected) !== JSON.stringify(registered)) {
            throw new Error(
                'The MCP tool catalog and runtime registry differ. Regenerate the MCP definitions before the SDK.'
            )
        }
        const readResult = readHandlerResultTypes(repoRoot)
        for (const toolName of registered) {
            const source = definitions.get(toolName)
            const config = source?.config
            const names =
                toolName === 'execute-sql'
                    ? { namespace: 'queries', method: 'sql' }
                    : config?.sdk
                      ? { ...config.sdk }
                      : {
                            namespace:
                                source?.moduleName === 'query-wrappers'
                                    ? 'queries'
                                    : camelCase(source?.moduleName ?? catalog[toolName].feature ?? 'utilities'),
                            method: camelCase(toolName),
                        }
            if (config?.confirmed_action && config.sdk) {
                names.method += toolName.endsWith('-prepare') ? 'Prepare' : 'Execute'
            }
            let operation
            try {
                operation = resolveSharedOperation({
                    api: schema,
                    inputSchema: inputs[toolName],
                    resultType: sharedResultType(toolName, source, schema, querySchema, readResult),
                    source,
                    metadata: catalog[toolName],
                    toolName,
                    names,
                    repoRoot,
                })
            } catch (cause) {
                throw new Error(`${toolName}: ${cause.message}`, { cause })
            }
            const method = `${operation.namespace}.${operation.method}`
            if (methodNames.has(method)) {
                throw new Error(`Duplicate SDK method ${method}`)
            }
            methodNames.add(method)
            operations.push(operation)
            coverage.push({ toolName, status: 'exported', method })
        }
        operations.sort((a, b) => `${a.namespace}.${a.method}`.localeCompare(`${b.namespace}.${b.method}`))
        if (!dryRun) {
            await emitSdk(operations, staging, { coverage })
            for (const artifact of ['src/generated', 'api-index.tsv', 'domains.tsv', 'coverage.json']) {
                await fs.mkdir(path.dirname(path.join(outputDir, artifact)), { recursive: true })
                await fs.rm(path.join(outputDir, artifact), { recursive: true, force: true })
                await fs.rename(path.join(staging, artifact), path.join(outputDir, artifact))
            }
        }
    } finally {
        await fs.rm(staging, { recursive: true, force: true })
    }
    return { exported: operations.length, coverage }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
    generateSdk()
        .then((result) => process.stdout.write(`SDK: all ${result.exported} MCP tools exported\n`))
        .catch((error) => {
            console.error(error)
            process.exitCode = 1
        })
}
