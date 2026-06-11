// Aliases generated *Api types back to their authored schema.ts source.
//
// OpenAPI components tagged `x-schema-source: posthog.schema.*` are machine
// projections of frontend-authored types (schema.ts -> schema.py -> OpenAPI).
// Re-emitting them through Orval produces a second, lossier TypeScript copy of
// a type the frontend already has (discriminators degrade, typed unions become
// `unknown`). This pass removes the emitted copy and re-exports the original:
//
//     export type { TrendsQuery as TrendsQueryApi } from '~/queries/schema/schema-general'
//
// Provenance comes from the tags, never from name matching. Enum components
// are skipped: Orval emits them as a const + type pair and code may reference
// the const values, while schema.ts often models them as bare string-literal
// unions with no runtime value. Components whose tag has no matching exported
// TS declaration (e.g. codegen-dedup names like `Foo1`) are skipped too.

import fs from 'node:fs'
import path from 'node:path'

const SCHEMA_SOURCE_KEY = 'x-schema-source'
const KERNEL_SOURCE_PREFIX = 'posthog.schema.'
const TS_EXPORT_RE = /^export (?:declare )?(interface|type|enum|const enum|class) (\w+)/gm

/** Map exported type name -> { module, kind } for every schema.ts source file. */
export function buildSchemaSourceIndex(repoRoot) {
    const index = new Map()
    const schemaDir = path.join(repoRoot, 'frontend/src/queries/schema')
    const sources = fs
        .readdirSync(schemaDir)
        .filter((f) => f.endsWith('.ts'))
        .sort()
        .map((f) => ({
            file: path.join(schemaDir, f),
            module: `~/queries/schema/${f.replace(/\.ts$/, '')}`,
        }))
    // schema.json generation follows imports into ~/types, so kernel-tagged
    // components can also originate from handwritten types.ts declarations
    sources.push({ file: path.join(repoRoot, 'frontend/src/types.ts'), module: '~/types' })

    for (const { file, module } of sources) {
        const text = fs.readFileSync(file, 'utf8')
        for (const match of text.matchAll(TS_EXPORT_RE)) {
            const [, kind, name] = match
            if (!index.has(name)) {
                index.set(name, { module, kind })
            }
        }
    }
    return index
}

/** Component name -> schema for every kernel-tagged component in the spec. */
export function collectKernelComponents(spec) {
    const kernel = new Map()
    for (const [name, schema] of Object.entries(spec?.components?.schemas ?? {})) {
        const source = schema?.[SCHEMA_SOURCE_KEY]
        if (typeof source === 'string' && source.startsWith(KERNEL_SOURCE_PREFIX)) {
            kernel.set(name, schema)
        }
    }
    return kernel
}

function findDeclBlock(text, generatedName) {
    const interfaceNeedle = `export interface ${generatedName} `
    const typeNeedle = `export type ${generatedName} =`
    const constNeedle = `export const ${generatedName} `

    if (text.includes(constNeedle)) {
        return { isValueExport: true }
    }

    let start = text.indexOf(interfaceNeedle)
    let end = -1
    if (start !== -1) {
        const braceStart = text.indexOf('{', start)
        let depth = 0
        for (let i = braceStart; i < text.length; i++) {
            if (text[i] === '{') {
                depth++
            } else if (text[i] === '}') {
                depth--
                if (depth === 0) {
                    end = i + 1
                    break
                }
            }
        }
    } else {
        start = text.indexOf(typeNeedle)
        if (start === -1) {
            return null
        }
        // a type alias ends where the next top-level statement begins
        const tail = text.slice(start)
        const next = tail.slice(1).search(/\n(?:export |\/\*\*|\/\/)/)
        end = next === -1 ? text.length : start + 1 + next
    }
    if (end === -1) {
        return null
    }

    // absorb the JSDoc block directly above the declaration
    let docStart = start
    const before = text.slice(0, start)
    const trimmed = before.trimEnd()
    if (trimmed.endsWith('*/')) {
        const open = trimmed.lastIndexOf('/**')
        if (open !== -1) {
            docStart = open
        }
    }
    // absorb trailing newlines so removal doesn't leave gaps
    while (end < text.length && text[end] === '\n') {
        end++
    }
    return { start: docStart, end }
}

/**
 * Rewrite a generated api.schemas.ts: emitted kernel twins become re-export
 * aliases of their authored schema.ts declarations. Returns stats.
 */
export function aliasKernelTypes(schemasFile, kernelComponents, sourceIndex) {
    let text = fs.readFileSync(schemasFile, 'utf8')
    const importsByModule = new Map()
    const aliasLines = []
    const stats = { aliased: 0, skippedEnum: 0, skippedNoSource: 0, skippedValueExport: 0 }

    for (const [name, schema] of kernelComponents) {
        const source = sourceIndex.get(name)
        if (!source) {
            stats.skippedNoSource++
            continue
        }
        if (schema.enum !== undefined || schema.const !== undefined || source.kind === 'enum') {
            stats.skippedEnum++
            continue
        }
        const block = findDeclBlock(text, `${name}Api`)
        if (!block) {
            continue // not emitted in this file
        }
        if (block.isValueExport) {
            stats.skippedValueExport++
            continue
        }
        text = text.slice(0, block.start) + text.slice(block.end)
        if (!importsByModule.has(source.module)) {
            importsByModule.set(source.module, [])
        }
        importsByModule.get(source.module).push(name)
        // a plain re-export would not create a local binding, and sibling
        // declarations in this file reference the *Api name — alias locally
        aliasLines.push(`export type ${name}Api = ${name}`)
        stats.aliased++
    }

    if (aliasLines.length > 0) {
        const importLines = [...importsByModule.entries()]
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([module, names]) => `import type { ${names.sort().join(', ')} } from '${module}'`)
        const banner =
            '// Kernel types below are authored in frontend/src/queries/schema (x-schema-source:\n' +
            '// posthog.schema.*) — aliased instead of re-emitting a lossy generated copy.\n'
        text = `${banner}${importLines.join('\n')}\n\n${aliasLines.sort().join('\n')}\n\n${text}`
        fs.writeFileSync(schemasFile, text)
    }
    return stats
}
