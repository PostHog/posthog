/**
 * Server-side TS → JS compile pipeline for custom tools.
 *
 * On write_file of a tools/<id>/source.ts, the server pipes the source through
 * esbuild, writes tools/<id>/compiled.js, extracts the schema/inputs from the
 * defineTool call, and writes schema.json + inputs.json.
 *
 * v1 uses a minimal AST-free extractor that accepts a `defineTool({ id, description,
 * inputs, actions })` literal at the bottom of the file. A more sophisticated
 * version (using a TS compiler API or a runtime sandbox eval) is a follow-up.
 *
 * Real esbuild integration is dynamically required so this module remains
 * importable in tests without the esbuild binary present.
 */

export interface CompileResult {
    compiledJs: string
    schemaJson: ToolSchemaShape
    inputsJson: ToolInputShape[]
}

export interface ToolSchemaShape {
    id: string
    description: string
    actions: Array<{ name: string; description: string; args?: Record<string, unknown> }>
}

export interface ToolInputShape {
    name: string
    description?: string
    secret?: boolean
}

export interface Compiler {
    compile(source: string, toolId: string): Promise<CompileResult>
}

/**
 * Minimal compiler suitable for tests and dev mode. Treats the source as plain
 * JS (strips type annotations naively via a regex), and expects the tool
 * definition to be exported in a specific shape:
 *
 *     defineTool({
 *         id: "...",
 *         description: "...",
 *         actions: { name: (args) => {...} },
 *         inputs: [...]
 *     })
 *
 * Tests pass through `simpleStripTypes()` so they don't need esbuild on PATH.
 * Production should swap this for the esbuild impl.
 */
export class SimpleCompiler implements Compiler {
    async compile(source: string, toolId: string): Promise<CompileResult> {
        const compiledJs = simpleStripTypes(source)
        const schema = extractSchema(source, toolId)
        return {
            compiledJs,
            schemaJson: schema.schema,
            inputsJson: schema.inputs,
        }
    }
}

/** Strip very basic TS annotations. Naive but enough for tool source. */
export function simpleStripTypes(source: string): string {
    return (
        source
            // strip ": Type" annotations after identifiers (very rough)
            .replace(/(:\s*[A-Za-z_$][\w$<>,\s|&[\]?'"]*)(?=[,)=;\s{])/g, '')
            // strip "as Type" expressions
            .replace(/\bas\s+[A-Za-z_$][\w$.<>,\s|&[\]?'"]*/g, '')
    )
}

interface ExtractedSchema {
    schema: ToolSchemaShape
    inputs: ToolInputShape[]
}

function extractSchema(source: string, fallbackId: string): ExtractedSchema {
    const idMatch = /id:\s*["']([\w.-]+)["']/.exec(source)
    const descMatch = /description:\s*["']([^"']+)["']/.exec(source)
    const id = idMatch?.[1] ?? fallbackId
    const description = descMatch?.[1] ?? `custom tool ${id}`

    const actionsBlock = matchActionsBlock(source)
    const actions = actionsBlock
        ? parseActionList(actionsBlock).map((name) => ({ name, description: `${id}.${name}` }))
        : [{ name: 'default', description: id }]

    const inputs = matchInputsBlock(source)
    return {
        schema: { id, description, actions },
        inputs,
    }
}

function matchActionsBlock(source: string): string | null {
    const start = source.search(/actions:\s*\{/)
    if (start === -1) {
        return null
    }
    const openIdx = source.indexOf('{', start)
    if (openIdx === -1) {
        return null
    }
    let depth = 0
    for (let i = openIdx; i < source.length; i++) {
        const ch = source[i]
        if (ch === '{') {
            depth++
        } else if (ch === '}') {
            depth--
            if (depth === 0) {
                return source.slice(openIdx + 1, i)
            }
        }
    }
    return null
}

function parseActionList(block: string): string[] {
    // Find top-level keys (identifiers followed by ':') in the actions object.
    // Skip string literals and bracket-balanced subexpressions.
    const names: string[] = []
    let depth = 0
    let i = 0
    while (i < block.length) {
        const ch = block[i]
        if (ch === '"' || ch === "'" || ch === '`') {
            const quote = ch
            i++
            while (i < block.length && block[i] !== quote) {
                if (block[i] === '\\') {
                    i++
                }
                i++
            }
            i++
            continue
        }
        if (ch === '{' || ch === '(' || ch === '[') {
            depth++
            i++
            continue
        }
        if (ch === '}' || ch === ')' || ch === ']') {
            depth--
            i++
            continue
        }
        if (depth === 0 && /[A-Za-z_$]/.test(ch)) {
            const m = /^([A-Za-z_$][\w$]*)\s*:/.exec(block.slice(i))
            if (m) {
                names.push(m[1])
                i += m[0].length
                continue
            }
        }
        i++
    }
    return [...new Set(names)]
}

function matchInputsBlock(source: string): ToolInputShape[] {
    const m = /inputs:\s*\[([\s\S]*?)\]/.exec(source)
    if (!m) {
        return []
    }
    const out: ToolInputShape[] = []
    const entryRe = /\{([^}]+)\}/g
    let entry: RegExpExecArray | null
    while ((entry = entryRe.exec(m[1]))) {
        const block = entry[1]
        const nameMatch = /name:\s*["']([^"']+)["']/.exec(block)
        if (!nameMatch) {
            continue
        }
        const descMatch = /description:\s*["']([^"']+)["']/.exec(block)
        const secretMatch = /secret:\s*(true|false)/.exec(block)
        out.push({
            name: nameMatch[1],
            description: descMatch?.[1],
            secret: secretMatch?.[1] === 'true',
        })
    }
    return out
}
