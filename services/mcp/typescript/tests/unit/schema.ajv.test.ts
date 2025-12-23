// services/mcp/typescript/tests/unit/schema.ajv.test.ts
// Guard test: compiles MCP tool input schemas with AJV in strict mode.
// Uses the generated schema at services/mcp/schema/tool-inputs.json to catch
// invalid or Ajv-strict-incompatible changes early in CI.
import Ajv from 'ajv'
import addFormats from 'ajv-formats'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from 'vitest'

test('AJV strict compiles all MCP tool input schemas', async () => {
    // Resolve ../../schema/tool-inputs.json relative to this test file
    const __filename = fileURLToPath(import.meta.url)
    const __dirname = path.dirname(__filename)
    const schemaPath = path.resolve(__dirname, '../../../schema/tool-inputs.json')

    let doc: unknown
    try {
        const src = await readFile(schemaPath, 'utf8')
        doc = JSON.parse(src)
    } catch {
        // Guidance if the generated schema file is missing
        throw new Error(
            `Could not read schema file at ${schemaPath}.
If this package generates schemas, run: pnpm --dir services/mcp schema:build:json`
        )
    }

    // Support multiple shapes:
    // - { definitions: { [name]: schema } } (local generated schema)
    // - { tools: { [toolName]: schema } }
    // - { tools: Array<{ name, inputSchema }> }
    // - Plain array of { name, inputSchema }
    // - { [toolName]: schema }
    const extract = (value: any): Array<{ name: string; schema: any }> => {
        if (!value) {
            return []
        }
        if (Array.isArray(value)) {
            return value
                .map((t) => ('inputSchema' in t ? { name: t.name ?? 'unknown', schema: t.inputSchema } : null))
                .filter(Boolean) as Array<{ name: string; schema: any }>
        }
        if (value.definitions) {
            return extract(value.definitions)
        }
        if (value.tools) {
            return extract(value.tools)
        }
        if (typeof value === 'object') {
            return Object.entries(value).map(([name, schema]) => ({ name, schema }))
        }
        return []
    }

    const items = extract(doc)
    expect(items.length).toBeGreaterThan(0)

    // Ajv strict mode surfaces schema issues (e.g. duplicate enum values, invalid unions)
    const ajv = new Ajv({
        strict: true,
        allErrors: true,
        allowUnionTypes: true,
    })
    addFormats(ajv)

    const failures: Array<{ name: string; error: unknown }> = []
    for (const { name, schema } of items) {
        try {
            ajv.compile(schema)
        } catch (err) {
            failures.push({ name, error: err })
        }
    }

    // If this assertion fails, at least one tool input schema is invalid under Ajv strict mode.
    expect(failures, JSON.stringify(failures, null, 2)).toHaveLength(0)
})
