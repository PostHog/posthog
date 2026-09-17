import ts from 'typescript'

type ListAppCall = { detail_tool: string; detail_args: string }

export type ToolInputSchema = { type?: string; properties?: Record<string, unknown>; required?: string[] }

function argumentKeys(expression: string): string[] {
    const source = `(${expression})`
    const { diagnostics } = ts.transpileModule(source, { reportDiagnostics: true })
    if (diagnostics?.some((diagnostic) => diagnostic.category === ts.DiagnosticCategory.Error)) {
        throw new Error('detail_args must be a valid object literal')
    }
    const file = ts.createSourceFile('detail-args.ts', source, ts.ScriptTarget.Latest, true)
    const statement = file.statements[0]
    if (
        file.statements.length !== 1 ||
        !statement ||
        !ts.isExpressionStatement(statement) ||
        !ts.isParenthesizedExpression(statement.expression) ||
        !ts.isObjectLiteralExpression(statement.expression.expression)
    ) {
        throw new Error('detail_args must be an object literal with explicit argument keys')
    }

    return statement.expression.expression.properties.map((property) => {
        if (
            (!ts.isPropertyAssignment(property) && !ts.isShorthandPropertyAssignment(property)) ||
            (!ts.isIdentifier(property.name) && !ts.isStringLiteral(property.name))
        ) {
            throw new Error(
                'detail_args must use explicit argument keys; spreads and computed keys cannot be validated'
            )
        }
        return property.name.text
    })
}

export function validateListAppToolCall(
    appKey: string,
    config: ListAppCall,
    schema: ToolInputSchema | undefined
): void {
    const context = `List app "${appKey}" calling "${config.detail_tool}"`
    if (!schema) {
        throw new Error(
            `${context}: no input schema snapshot for this tool. Check the tool name, or run the tool schema snapshot test to record a new tool.`
        )
    }

    let keys: string[]
    try {
        keys = argumentKeys(config.detail_args)
    } catch (error) {
        throw new Error(`${context}: ${error instanceof Error ? error.message : String(error)}`)
    }

    if (schema.type !== 'object' || !schema.properties) {
        throw new Error(`${context}: the input schema must expose object properties to validate detail_args`)
    }
    const known = new Set(Object.keys(schema.properties))
    const unknown = keys.filter((key) => !known.has(key))
    const missing = (schema.required ?? []).filter((key) => !keys.includes(key))
    if (unknown.length || missing.length) {
        const problems = [
            ...(unknown.length ? [`Unknown arguments: ${unknown.join(', ')}`] : []),
            ...(missing.length ? [`Missing required arguments: ${missing.join(', ')}`] : []),
        ]
        throw new Error(`${context}: ${problems.join('. ')}. Check detail_args against the tool input schema.`)
    }
}
