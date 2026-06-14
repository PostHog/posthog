/**
 * Custom-tool upload pipeline: parse → AST shape check → esbuild → emit
 * `compiled.js`. Runs inside the `PUT /tools/:id` handler so shape failures
 * surface at upload time, not at session-start.
 *
 * Two distinct checks:
 *
 *   1. **AST shape check** — pure source-text analysis via the TypeScript
 *      compiler API. Walks the syntax tree without executing user code.
 *      Confirms exactly one `export default <ObjectLiteral>` with an
 *      `actions` property whose `default` entry is a function-shaped node.
 *      No `vm.runInContext`, no Modal sandbox — nothing runs, nothing to
 *      sandbox.
 *
 *   2. **esbuild transform** — TS → CJS, the same output the runner has
 *      loaded since day one. Runs only if the AST check passed.
 *
 * Failures bubble up as structured `ToolCompileError` objects. Each carries
 * a `kind` discriminator + a one-line `message` the caller (and the
 * concierge model) can surface verbatim.
 */

import { transform as esbuildTransform } from 'esbuild'
import ts from 'typescript'

export type ToolCompileErrorKind =
    | 'parse_failed'
    | 'ast_no_default_export'
    | 'ast_default_not_object'
    | 'ast_missing_actions'
    | 'ast_actions_not_object'
    | 'ast_missing_default_action'
    | 'ast_default_action_not_callable'
    | 'ast_dynamic_export'
    | 'transform_failed'

export interface ToolCompileError {
    kind: ToolCompileErrorKind
    message: string
    /** Source position where the error was detected, if known (1-based). */
    line?: number
    column?: number
}

export interface CompileTypedToolResult {
    ok: boolean
    /** When ok: the CJS-shaped compiled.js the runner will load at session start. */
    compiled_js?: string
    /** Always present; empty when ok. */
    errors: ToolCompileError[]
}

/**
 * Validate + compile one tool's source. Pure (no I/O, no globals); the
 * caller writes the result to the bundle store when ok.
 */
export async function compileTypedTool(args: { tool_id: string; source: string }): Promise<CompileTypedToolResult> {
    const sf = ts.createSourceFile(
        `${args.tool_id}.ts`,
        args.source,
        ts.ScriptTarget.ES2022,
        /* setParentNodes */ true,
        ts.ScriptKind.TS
    )

    const astErrors = checkExportShape(sf)
    if (astErrors.length > 0) {
        return { ok: false, errors: astErrors }
    }

    try {
        const out = await esbuildTransform(args.source, {
            loader: 'ts',
            format: 'cjs',
            target: 'node20',
        })
        return { ok: true, compiled_js: out.code, errors: [] }
    } catch (err) {
        return {
            ok: false,
            errors: [
                {
                    kind: 'transform_failed',
                    message: `esbuild failed: ${(err as Error).message.split('\n')[0]}`,
                },
            ],
        }
    }
}

// ─── AST shape check ─────────────────────────────────────────────────

/**
 * Walk the syntax tree, confirm there's exactly one `export default
 * <ObjectLiteral>` with an `actions.default` function-shaped property.
 * No type-checking, no symbol resolution — the source-file parse is enough.
 */
function checkExportShape(sf: ts.SourceFile): ToolCompileError[] {
    const errors: ToolCompileError[] = []

    // Collect:
    //   1. `export default <expr>`  — `ExportAssignment` with !isExportEquals
    //   2. `export default function foo() {}` / `export default class Bar {}`
    //      — these are `FunctionDeclaration` / `ClassDeclaration` nodes with
    //      `export` + `default` modifiers, NOT ExportAssignments. Easy to
    //      miss; the bare-function concierge foot-gun ships exactly this
    //      shape.
    const defaultExports: { node: ts.Node; expr: ts.Expression | null }[] = []
    for (const stmt of sf.statements) {
        if (ts.isExportAssignment(stmt) && !stmt.isExportEquals) {
            defaultExports.push({ node: stmt, expr: stmt.expression })
        } else if (
            (ts.isFunctionDeclaration(stmt) || ts.isClassDeclaration(stmt)) &&
            hasModifier(stmt, ts.SyntaxKind.ExportKeyword) &&
            hasModifier(stmt, ts.SyntaxKind.DefaultKeyword)
        ) {
            // The function/class declaration IS the export — there's no
            // wrapped expression, so we keep `expr: null` and the caller
            // treats it as "default export but not an object literal".
            defaultExports.push({ node: stmt, expr: null })
        }
    }

    if (defaultExports.length === 0) {
        errors.push({
            kind: 'ast_no_default_export',
            message: 'tool source must `export default { actions: { default: fn } }` — no `export default` found',
        })
        return errors
    }
    if (defaultExports.length > 1) {
        const dup = defaultExports[1].node
        const pos = sf.getLineAndCharacterOfPosition(dup.getStart(sf))
        errors.push({
            kind: 'ast_no_default_export',
            message: 'tool source must have exactly one `export default` — exactly one found is required',
            line: pos.line + 1,
            column: pos.character + 1,
        })
        return errors
    }

    // `export default function foo() {}` or `export default class Bar {}` —
    // these are never the right shape. Report up front.
    if (defaultExports[0].expr === null) {
        const node = defaultExports[0].node
        const pos = sf.getLineAndCharacterOfPosition(node.getStart(sf))
        errors.push({
            kind: 'ast_default_not_object',
            message:
                'tool source must export an object, not a bare function or class. Wrap as `export default { actions: { default: <your function> } }`',
            line: pos.line + 1,
            column: pos.character + 1,
        })
        return errors
    }

    const expr = unwrap(defaultExports[0].expr)

    if (!ts.isObjectLiteralExpression(expr)) {
        const pos = sf.getLineAndCharacterOfPosition(expr.getStart(sf))
        if (ts.isFunctionExpression(expr) || ts.isArrowFunction(expr)) {
            errors.push({
                kind: 'ast_default_not_object',
                message:
                    'tool source must export an object, not a bare function. Wrap as `export default { actions: { default: <your function> } }`',
                line: pos.line + 1,
                column: pos.character + 1,
            })
        } else if (ts.isCallExpression(expr) || ts.isNewExpression(expr) || ts.isIdentifier(expr)) {
            errors.push({
                kind: 'ast_dynamic_export',
                message:
                    'tool definitions must be statically declared object literals. `export default makeTool()` / factory calls / identifier references are not allowed — the platform analyses the export shape ahead of run-time.',
                line: pos.line + 1,
                column: pos.character + 1,
            })
        } else {
            errors.push({
                kind: 'ast_default_not_object',
                message: `tool source must export an object literal — got ${ts.SyntaxKind[expr.kind]}`,
                line: pos.line + 1,
                column: pos.character + 1,
            })
        }
        return errors
    }

    const actionsProp = findProperty(expr, 'actions')
    if (!actionsProp) {
        errors.push({
            kind: 'ast_missing_actions',
            message: 'tool export object is missing required `actions` property — write `{ actions: { default: fn } }`',
        })
        return errors
    }

    const actionsValue = unwrap(actionsProp.initializer)
    if (!ts.isObjectLiteralExpression(actionsValue)) {
        const pos = sf.getLineAndCharacterOfPosition(actionsValue.getStart(sf))
        errors.push({
            kind: 'ast_actions_not_object',
            message: `\`actions\` must be an object literal — got ${ts.SyntaxKind[actionsValue.kind]}`,
            line: pos.line + 1,
            column: pos.character + 1,
        })
        return errors
    }

    const defaultProp = findProperty(actionsValue, 'default')
    if (!defaultProp) {
        errors.push({
            kind: 'ast_missing_default_action',
            message:
                '`actions.default` is required — the runner always dispatches `action: "default"`. Add a `default: (args, ctx) => { ... }` entry inside `actions`.',
        })
        return errors
    }

    const defaultValue = unwrap(defaultProp.initializer)
    if (!isCallable(defaultValue)) {
        const pos = sf.getLineAndCharacterOfPosition(defaultValue.getStart(sf))
        errors.push({
            kind: 'ast_default_action_not_callable',
            message: `\`actions.default\` must be a function (arrow or function expression). Got ${ts.SyntaxKind[defaultValue.kind]}.`,
            line: pos.line + 1,
            column: pos.character + 1,
        })
        return errors
    }

    return errors
}

function hasModifier(
    node: ts.FunctionDeclaration | ts.ClassDeclaration,
    kind: ts.SyntaxKind.ExportKeyword | ts.SyntaxKind.DefaultKeyword
): boolean {
    const mods = (node as ts.HasModifiers).modifiers
    if (!mods) {
        return false
    }
    for (const m of mods) {
        if (m.kind === kind) {
            return true
        }
    }
    return false
}

function unwrap(node: ts.Expression): ts.Expression {
    let cur: ts.Expression = node
    while (ts.isAsExpression(cur) || ts.isTypeAssertionExpression(cur) || ts.isParenthesizedExpression(cur)) {
        cur = (cur as ts.AsExpression | ts.TypeAssertion | ts.ParenthesizedExpression).expression
    }
    return cur
}

function findProperty(obj: ts.ObjectLiteralExpression, name: string): ts.PropertyAssignment | undefined {
    for (const member of obj.properties) {
        if (ts.isPropertyAssignment(member)) {
            const key = member.name
            if (ts.isIdentifier(key) && key.text === name) {
                return member
            }
            if (ts.isStringLiteral(key) && key.text === name) {
                return member
            }
        }
    }
    return undefined
}

function isCallable(node: ts.Expression): boolean {
    return ts.isArrowFunction(node) || ts.isFunctionExpression(node)
}
