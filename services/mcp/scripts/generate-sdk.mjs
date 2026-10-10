#!/usr/bin/env node
import { createHash } from 'node:crypto'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse } from 'yaml'

import { findOperation } from './lib/agent-operations.mjs'
import { discoverDefinitions, resolveSchemaPath } from './lib/definitions.mjs'
import { emitSdk } from './lib/sdk-emitter.mjs'
import { readHandlerResultTypes } from './lib/sdk-handler-types.mjs'
import { buildSdkHandlers } from './lib/sdk-handlers.mjs'
import { sharedResultType } from './lib/sdk-output-adapters.mjs'
import { resolveQueryOperation, resolveSqlOperation } from './lib/sdk-query-adapter.mjs'
import { annotateDocumentation, resolveSdkOperation, unsupportedReason } from './lib/sdk-schema.mjs'
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
    const catalog = JSON.parse(
        await fs.readFile(path.join(repoRoot, 'services/mcp/schema/tool-definitions-all.json'), 'utf8')
    )
    const operations = []
    const coverage = []
    const methodNames = new Set()
    // A failed generation must not leave a partly refreshed public contract.
    const staging = await fs.mkdtemp(path.join(path.dirname(outputDir), '.sdk-generated-'))
    try {
        const inputs = await buildSdkHandlers(repoRoot, path.join(staging, 'src/generated/handlers.mjs'))
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
            const names = config?.sdk
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
                if (toolName === 'execute-sql') {
                    operation = resolveSqlOperation(schema, querySchema, catalog[toolName], repoRoot)
                } else if (
                    config?.sdk &&
                    !unsupportedReason(
                        config,
                        source.category,
                        config.operation && findOperation(schema, config.operation)
                    )
                ) {
                    operation = config.operation
                        ? resolveSdkOperation(schema, config, source.category, toolName, source.filePath, repoRoot)
                        : resolveQueryOperation(
                              schema,
                              querySchema,
                              config,
                              source.category,
                              toolName,
                              source.filePath,
                              repoRoot
                          )
                } else {
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
                }
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
        const schemaHash = createHash('sha256')
            .update(JSON.stringify(operations.map((item) => item.registry.schemas)))
            .digest('hex')
        const sourceRevision = createHash('sha256')
            .update(JSON.stringify(operations.map(({ registry, ...item }) => item)))
            .update(await fs.readFile(path.join(staging, 'src/generated/handlers.mjs')))
            .digest('hex')
        const { version } = JSON.parse(await fs.readFile(path.join(repoRoot, 'packages/sdk/package.json'), 'utf8'))
        if (!dryRun) {
            await emitSdk(operations, staging, { packageVersion: version, sourceRevision, schemaHash, coverage })
            for (const artifact of ['src/generated', 'catalog', 'catalog.json', 'coverage.json']) {
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
