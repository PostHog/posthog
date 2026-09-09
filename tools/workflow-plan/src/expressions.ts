import { Evaluator, Lexer, Parser, data } from '@actions/expressions'

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }
export type Context = Record<string, JsonValue>

export interface ExpressionFunction {
    name: string
    minArgs: number
    maxArgs: number
    call: (...args: data.ExpressionData[]) => data.ExpressionData
}

export interface StatusState {
    dependenciesSucceeded: boolean
    dependenciesFailed: boolean
    cancelled: boolean
}

export const CONTEXT_NAMES = [
    'github',
    'needs',
    'vars',
    'env',
    'inputs',
    'steps',
    'secrets',
    'runner',
    'job',
    'matrix',
    'strategy',
]

// GitHub applies success() implicitly when an `if:` names no status function.
const STATUS_FUNCTION = /\b(success|failure|cancelled|always)\s*\(/i
const WHOLE_EXPRESSION = /^\$\{\{([\s\S]*)\}\}$/
const EMBEDDED_EXPRESSION = /\$\{\{([\s\S]*?)\}\}/g

export const HASH_FILES_STUB = 'workflow-plan-stub-hash'

export function toExpressionData(value: JsonValue | undefined): data.ExpressionData {
    if (value === null || value === undefined) {
        return new data.Null()
    }
    if (typeof value === 'string') {
        return new data.StringData(value)
    }
    if (typeof value === 'number') {
        return new data.NumberData(value)
    }
    if (typeof value === 'boolean') {
        return new data.BooleanData(value)
    }
    if (Array.isArray(value)) {
        const array = new data.Array()
        for (const item of value) {
            array.add(toExpressionData(item))
        }
        return array
    }
    const dictionary = new data.Dictionary()
    for (const [key, item] of Object.entries(value)) {
        dictionary.add(key, toExpressionData(item))
    }
    return dictionary
}

function booleanFunction(name: string, value: () => boolean): [string, ExpressionFunction] {
    return [name, { name, minArgs: 0, maxArgs: 0, call: () => new data.BooleanData(value()) }]
}

export function statusFunctions(state: StatusState): Map<string, ExpressionFunction> {
    return new Map<string, ExpressionFunction>([
        booleanFunction('success', () => state.dependenciesSucceeded && !state.cancelled),
        booleanFunction('failure', () => state.dependenciesFailed),
        booleanFunction('cancelled', () => state.cancelled),
        booleanFunction('always', () => true),
        [
            'hashfiles',
            {
                name: 'hashFiles',
                minArgs: 1,
                maxArgs: 255,
                call: () => new data.StringData(HASH_FILES_STUB),
            },
        ],
    ])
}

function isTruthy(value: data.ExpressionData): boolean {
    switch (value.kind) {
        case data.Kind.Null:
            return false
        case data.Kind.Boolean:
            return value.coerceString() === 'true'
        case data.Kind.Number: {
            const number = value.number()
            return number !== 0 && !Number.isNaN(number)
        }
        case data.Kind.String:
            return value.coerceString() !== ''
        default:
            return true
    }
}

export function evaluateExpression(
    expression: string,
    context: Context,
    functions: Map<string, ExpressionFunction>
): data.ExpressionData {
    const tokens = new Lexer(expression).lex().tokens
    const functionInfos = [...functions.values()].map(({ name, minArgs, maxArgs }) => ({ name, minArgs, maxArgs }))
    const ast = new Parser(tokens, CONTEXT_NAMES, functionInfos).parse()
    return new Evaluator(ast, toExpressionData(context) as data.Dictionary, functions).evaluate()
}

export function fromExpressionData(value: data.ExpressionData): JsonValue {
    switch (value.kind) {
        case data.Kind.Null:
            return null
        case data.Kind.Boolean:
            return value.coerceString() === 'true'
        case data.Kind.Number:
            return value.number()
        case data.Kind.String:
            return value.coerceString()
        case data.Kind.Array:
            return (value as data.Array).values().map(fromExpressionData)
        default:
            return Object.fromEntries(
                (value as data.Dictionary).pairs().map((pair) => [pair.key, fromExpressionData(pair.value)])
            )
    }
}

/** Evaluates a YAML value that may be one whole expression, a template, or a plain literal, keeping structure. */
export function evaluateValue(raw: unknown, context: Context, functions: Map<string, ExpressionFunction>): unknown {
    if (typeof raw !== 'string') {
        return raw
    }
    const wrapped = WHOLE_EXPRESSION.exec(raw.trim())
    if (wrapped) {
        return fromExpressionData(evaluateExpression(wrapped[1]!.trim(), context, functions))
    }
    return raw.includes('${{') ? JSON.parse(evaluateTemplate(raw, context, functions)) : raw
}

export function evaluateCondition(raw: unknown, context: Context, functions: Map<string, ExpressionFunction>): boolean {
    if (raw === undefined || raw === null) {
        return evaluateCondition('success()', context, functions)
    }
    let expression = String(raw).trim()
    const wrapped = WHOLE_EXPRESSION.exec(expression)
    if (wrapped) {
        expression = wrapped[1]!.trim()
    }
    if (!STATUS_FUNCTION.test(expression)) {
        expression = `success() && (${expression})`
    }
    return isTruthy(evaluateExpression(expression, context, functions))
}

export function evaluateTemplate(raw: unknown, context: Context, functions: Map<string, ExpressionFunction>): string {
    if (typeof raw !== 'string') {
        return raw === undefined || raw === null ? '' : String(raw)
    }
    return raw.replace(EMBEDDED_EXPRESSION, (_, expression: string) =>
        evaluateExpression(expression.trim(), context, functions).coerceString()
    )
}

export function containsExpression(raw: unknown): boolean {
    return typeof raw === 'string' && raw.includes('${{')
}
