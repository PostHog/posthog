/**
 * Static matcher for the no-sandbox fast path (spec §4.2): a `run` script
 * qualifies iff it is exactly one SDK call with JSON-literal-constructible
 * arguments on the default `client` import —
 *
 *     import { client } from '@posthog/sdk'
 *     export default await client.<domain>.<method>(<literal args>)
 *
 * or the two-statement `const x = await client.<domain>.<method>(…)` /
 * `export default x` pair. Type-only imports and comments are fine; ANY other
 * statement, identifier argument, computed value, ternary, or chained call
 * disqualifies the script. Constant folding of literals is the ceiling — never
 * widen this toward an interpreter (a "small TS interpreter" is a second
 * sandbox with none of the isolation). A miss is never an error: the caller
 * falls through to the compile-gate → executor path.
 */

import type TS from 'typescript'

export interface FastPathMatch {
    /** `<domain>.<method>` exactly as written on the `client` binding. */
    methodId: string
    /** Extracted literal call arguments — zero or one, per the SDK surface. */
    args: unknown[]
}

const SDK_MODULE_SPECIFIER = '@posthog/sdk'
const CLIENT_BINDING = 'client'

/**
 * Match a script against the fast-path subset. Returns `null` on any
 * deviation — including when `typescript` itself is unavailable (the
 * distributed CLI bundle ships without it), making the fast path a pure
 * optimization the sandbox path never depends on.
 */
export async function matchFastPath(source: string): Promise<FastPathMatch | null> {
    let ts: typeof TS
    try {
        ts = (await import('typescript')).default
    } catch {
        return null
    }

    const sourceFile = ts.createSourceFile('script.ts', source, ts.ScriptTarget.ES2022, true)
    // The parser recovers from syntax errors with a best-effort AST — never
    // dispatch one; the compile gate reports the syntax error properly.
    const parseDiagnostics = (sourceFile as unknown as { parseDiagnostics?: unknown[] }).parseDiagnostics
    if (parseDiagnostics === undefined || parseDiagnostics.length > 0) {
        return null
    }

    let sawClientImport = false
    let constBinding: { name: string; call: TS.CallExpression } | null = null
    let exported: { kind: 'call'; call: TS.CallExpression } | { kind: 'identifier'; name: string } | null = null

    for (const statement of sourceFile.statements) {
        if (ts.isImportDeclaration(statement)) {
            if (statement.importClause?.isTypeOnly) {
                continue
            }
            if (!isClientImport(ts, statement) || sawClientImport) {
                return null
            }
            sawClientImport = true
            continue
        }

        if (ts.isVariableStatement(statement)) {
            // Only the single `const x = await client.<a>.<b>(…)` pairing shape.
            if (constBinding !== null || exported !== null) {
                return null
            }
            if ((statement.declarationList.flags & ts.NodeFlags.Const) === 0) {
                return null
            }
            if (statement.modifiers !== undefined && statement.modifiers.length > 0) {
                return null
            }
            const declarations = statement.declarationList.declarations
            if (declarations.length !== 1) {
                return null
            }
            const declaration = declarations[0]!
            if (!ts.isIdentifier(declaration.name) || declaration.initializer === undefined) {
                return null
            }
            const call = asClientCall(ts, declaration.initializer)
            if (call === null) {
                return null
            }
            constBinding = { name: declaration.name.text, call }
            continue
        }

        if (ts.isExportAssignment(statement) && !statement.isExportEquals) {
            if (exported !== null) {
                return null
            }
            const expression = unwrapAwait(ts, statement.expression)
            if (ts.isIdentifier(expression)) {
                exported = { kind: 'identifier', name: expression.text }
                continue
            }
            const call = asClientCall(ts, statement.expression)
            if (call === null) {
                return null
            }
            exported = { kind: 'call', call }
            continue
        }

        // Any other statement has (potential) effects — sandbox.
        return null
    }

    if (!sawClientImport || exported === null) {
        return null
    }

    let call: TS.CallExpression
    if (exported.kind === 'call') {
        if (constBinding !== null) {
            return null
        }
        call = exported.call
    } else {
        if (constBinding === null || constBinding.name !== exported.name) {
            return null
        }
        call = constBinding.call
    }

    return extractCall(ts, call)
}

/** Exactly `import { client } from '@posthog/sdk'` — type-only specifiers may ride along. */
function isClientImport(ts: typeof TS, statement: TS.ImportDeclaration): boolean {
    if (!ts.isStringLiteral(statement.moduleSpecifier) || statement.moduleSpecifier.text !== SDK_MODULE_SPECIFIER) {
        return false
    }
    const clause = statement.importClause
    if (clause === undefined || clause.name !== undefined) {
        return false
    }
    const bindings = clause.namedBindings
    if (bindings === undefined || !ts.isNamedImports(bindings)) {
        return false
    }
    const valueSpecifiers = bindings.elements.filter((element) => !element.isTypeOnly)
    return (
        valueSpecifiers.length === 1 &&
        valueSpecifiers[0]!.propertyName === undefined &&
        valueSpecifiers[0]!.name.text === CLIENT_BINDING
    )
}

/** Peel a single optional `await` — the executor awaits exports anyway, so both spellings are equivalent. */
function unwrapAwait(ts: typeof TS, expression: TS.Expression): TS.Expression {
    return ts.isAwaitExpression(expression) ? expression.expression : expression
}

/** The expression must be exactly `client.<domain>.<method>(…)` — no deeper chains, no optional chaining. */
function asClientCall(ts: typeof TS, expression: TS.Expression): TS.CallExpression | null {
    const unwrapped = unwrapAwait(ts, expression)
    if (!ts.isCallExpression(unwrapped) || unwrapped.typeArguments !== undefined) {
        return null
    }
    const method = unwrapped.expression
    if (!ts.isPropertyAccessExpression(method) || method.questionDotToken !== undefined) {
        return null
    }
    const domain = method.expression
    if (!ts.isPropertyAccessExpression(domain) || domain.questionDotToken !== undefined) {
        return null
    }
    if (!ts.isIdentifier(domain.expression) || domain.expression.text !== CLIENT_BINDING) {
        return null
    }
    return unwrapped
}

function extractCall(ts: typeof TS, call: TS.CallExpression): FastPathMatch | null {
    if (call.arguments.length > 1) {
        return null
    }
    const method = call.expression as TS.PropertyAccessExpression
    const domain = method.expression as TS.PropertyAccessExpression
    const methodId = `${domain.name.text}.${method.name.text}`

    const args: unknown[] = []
    for (const argument of call.arguments) {
        const extracted = extractLiteral(ts, argument)
        if (!extracted.ok) {
            return null
        }
        args.push(extracted.value)
    }
    return { methodId, args }
}

type ExtractedLiteral = { ok: true; value: unknown } | { ok: false }

const EXTRACT_FAILED: ExtractedLiteral = { ok: false }

/**
 * JSON-literal-constructible values only: string/number/boolean/null literals,
 * prefix-minus on numeric literals, substitution-free template literals, and
 * array/object literals thereof.
 */
function extractLiteral(ts: typeof TS, node: TS.Expression): ExtractedLiteral {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
        return { ok: true, value: node.text }
    }
    if (ts.isNumericLiteral(node)) {
        return { ok: true, value: Number(node.text) }
    }
    if (node.kind === ts.SyntaxKind.TrueKeyword) {
        return { ok: true, value: true }
    }
    if (node.kind === ts.SyntaxKind.FalseKeyword) {
        return { ok: true, value: false }
    }
    if (node.kind === ts.SyntaxKind.NullKeyword) {
        return { ok: true, value: null }
    }
    if (
        ts.isPrefixUnaryExpression(node) &&
        node.operator === ts.SyntaxKind.MinusToken &&
        ts.isNumericLiteral(node.operand)
    ) {
        return { ok: true, value: -Number(node.operand.text) }
    }
    if (ts.isArrayLiteralExpression(node)) {
        const values: unknown[] = []
        for (const element of node.elements) {
            if (ts.isOmittedExpression(element)) {
                return EXTRACT_FAILED
            }
            const extracted = extractLiteral(ts, element)
            if (!extracted.ok) {
                return EXTRACT_FAILED
            }
            values.push(extracted.value)
        }
        return { ok: true, value: values }
    }
    if (ts.isObjectLiteralExpression(node)) {
        const value: Record<string, unknown> = {}
        for (const property of node.properties) {
            // Shorthand, spread, computed keys, methods, accessors: all reach
            // beyond literals — disqualify.
            if (!ts.isPropertyAssignment(property)) {
                return EXTRACT_FAILED
            }
            const name = property.name
            if (!ts.isIdentifier(name) && !ts.isStringLiteral(name)) {
                return EXTRACT_FAILED
            }
            const extracted = extractLiteral(ts, property.initializer)
            if (!extracted.ok) {
                return EXTRACT_FAILED
            }
            value[name.text] = extracted.value
        }
        return { ok: true, value }
    }
    return EXTRACT_FAILED
}
