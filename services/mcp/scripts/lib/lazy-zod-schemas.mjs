/**
 * Rewrites the Zod schemas Orval emits into builder functions.
 *
 * Orval writes `export const X = zod.object({...})`. Every such constant is a
 * live object for the life of the process, and the MCP server ships ~2,800 of
 * them: about 450 MiB of heap per pod at boot. As `export const X = () =>
 * zod.object({...})` a schema exists only while a caller uses it, and building
 * one costs ~0.1 ms. References between exported schemas become calls.
 */
import ts from 'typescript'

/**
 * @param {string} source Orval output for one module.
 * @param {string} [fileName] Used for diagnostics only.
 * @returns {{ source: string, schemaCount: number, referenceCount: number }}
 */
export function lazifyZodSchemas(source, fileName = 'api.ts') {
    const sourceFile = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)

    const schemaDeclarations = []
    for (const statement of sourceFile.statements) {
        if (!ts.isVariableStatement(statement)) {
            continue
        }
        const declarations = statement.declarationList.declarations
        if (declarations.length !== 1) {
            continue
        }
        const declaration = declarations[0]
        if (!ts.isIdentifier(declaration.name) || !declaration.initializer) {
            continue
        }
        if (isRootedAtZod(declaration.initializer)) {
            schemaDeclarations.push(declaration)
        }
    }

    const schemaNames = new Set(schemaDeclarations.map((declaration) => declaration.name.text))
    /** @type {{ start: number, end: number, text: string }[]} */
    const edits = []
    let referenceCount = 0

    for (const declaration of schemaDeclarations) {
        const initializer = declaration.initializer
        // The range between `=` and the initializer holds only trivia (spaces and
        // any `@__PURE__` annotation); the builder replaces it.
        edits.push({ start: initializer.getFullStart(), end: initializer.getStart(sourceFile), text: ' () => ' })

        const visit = (node) => {
            if (ts.isIdentifier(node) && schemaNames.has(node.text) && isValueReference(node)) {
                referenceCount += 1
                if (ts.isShorthandPropertyAssignment(node.parent)) {
                    edits.push({
                        start: node.getStart(sourceFile),
                        end: node.getEnd(),
                        text: `${node.text}: ${node.text}()`,
                    })
                } else {
                    edits.push({ start: node.getStart(sourceFile), end: node.getEnd(), text: `${node.text}()` })
                }
            }
            ts.forEachChild(node, visit)
        }
        ts.forEachChild(initializer, visit)
    }

    edits.sort((a, b) => b.start - a.start)
    let output = source
    let previousStart = Number.POSITIVE_INFINITY
    for (const edit of edits) {
        if (edit.end > previousStart) {
            throw new Error(`${fileName}: overlapping edits while rewriting Zod schemas`)
        }
        output = output.slice(0, edit.start) + edit.text + output.slice(edit.end)
        previousStart = edit.start
    }

    return { source: output, schemaCount: schemaDeclarations.length, referenceCount }
}

/** True for `zod.x(...)`, `zod.x(...).y(...)`, `zod\n  .x(...)`; false for literals and for builders already rewritten. */
function isRootedAtZod(expression) {
    let node = expression
    while (
        ts.isPropertyAccessExpression(node) ||
        ts.isCallExpression(node) ||
        ts.isElementAccessExpression(node) ||
        ts.isParenthesizedExpression(node)
    ) {
        node = node.expression
    }
    return ts.isIdentifier(node) && node.text === 'zod'
}

/** False when the identifier names a property (`a.X`, `{ X: ... }`) instead of reading a variable. */
function isValueReference(identifier) {
    const parent = identifier.parent
    if (ts.isPropertyAccessExpression(parent) && parent.name === identifier) {
        return false
    }
    if (ts.isPropertyAssignment(parent) && parent.name === identifier) {
        return false
    }
    return true
}
