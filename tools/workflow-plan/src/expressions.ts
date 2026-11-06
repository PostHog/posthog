import { Evaluator, Lexer, Parser, data, wellKnownFunctions } from '@actions/expressions'
import type { FunctionDefinition } from '@actions/expressions/funcs/info'
import { TokenType } from '@actions/expressions/lexer'
import { truthy } from '@actions/expressions/result'

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }
export type Context = Record<string, JsonValue>
export type FunctionMap = Map<string, FunctionDefinition>

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
const STATUS_FUNCTIONS = new Set(['success', 'failure', 'cancelled', 'always'])
const WHOLE_EXPRESSION = /^\$\{\{([\s\S]*)\}\}$/
const EMBEDDED_EXPRESSION = /\$\{\{([\s\S]*?)\}\}/g

export const HASH_FILES_STUB = 'workflow-plan-stub-hash'

function booleanFunction(name: string, value: () => boolean): [string, FunctionDefinition] {
    return [name, { name, minArgs: 0, maxArgs: 0, call: () => new data.BooleanData(value()) }]
}

// An empty string is an output no script produced at plan time, so it resolves to null instead of failing.
const FROM_JSON_OR_NULL: FunctionDefinition = {
    name: 'fromJSON',
    minArgs: 1,
    maxArgs: 1,
    call: (...args) =>
        args[0]!.coerceString().trim() === '' ? new data.Null() : wellKnownFunctions['fromjson']!.call(...args),
}

export function planFunctions(state: StatusState): FunctionMap {
    return new Map<string, FunctionDefinition>([
        booleanFunction('success', () => state.dependenciesSucceeded && !state.cancelled),
        booleanFunction('failure', () => state.dependenciesFailed),
        booleanFunction('cancelled', () => state.cancelled),
        booleanFunction('always', () => true),
        [
            'hashfiles',
            { name: 'hashFiles', minArgs: 1, maxArgs: 255, call: () => new data.StringData(HASH_FILES_STUB) },
        ],
        ['fromjson', FROM_JSON_OR_NULL],
    ])
}

export function evaluateExpression(expression: string, context: Context, functions: FunctionMap): data.ExpressionData {
    const tokens = new Lexer(expression).lex().tokens
    const ast = new Parser(tokens, CONTEXT_NAMES, [...functions.values()]).parse()
    const contextData = JSON.parse(JSON.stringify(context), data.reviver) as data.Dictionary
    return new Evaluator(ast, contextData, functions).evaluate()
}

function unwrapExpression(raw: string): string | undefined {
    return WHOLE_EXPRESSION.exec(raw.trim())?.[1]?.trim()
}

/** Evaluates a YAML value that may be one whole expression, a template, or a plain literal, keeping structure. */
export function evaluateValue(raw: unknown, context: Context, functions: FunctionMap): unknown {
    if (typeof raw !== 'string') {
        return raw
    }
    const expression = unwrapExpression(raw)
    if (expression !== undefined) {
        return JSON.parse(JSON.stringify(evaluateExpression(expression, context, functions), data.replacer))
    }
    if (!raw.includes('${{')) {
        return raw
    }
    const evaluated = evaluateTemplate(raw, context, functions)
    try {
        return JSON.parse(evaluated)
    } catch {
        return evaluated
    }
}

function namesStatusFunction(expression: string): boolean {
    const tokens = new Lexer(expression).lex().tokens
    return tokens.some(
        (token, index) =>
            token.type === TokenType.IDENTIFIER &&
            STATUS_FUNCTIONS.has(token.lexeme.toLowerCase()) &&
            tokens[index + 1]?.type === TokenType.LEFT_PAREN
    )
}

export function evaluateCondition(raw: unknown, context: Context, functions: FunctionMap): boolean {
    if (raw === undefined || raw === null) {
        return truthy(functions.get('success')!.call())
    }
    let expression = unwrapExpression(String(raw)) ?? String(raw).trim()
    if (!namesStatusFunction(expression)) {
        expression = `success() && (${expression})`
    }
    return truthy(evaluateExpression(expression, context, functions))
}

export function evaluateTemplate(raw: unknown, context: Context, functions: FunctionMap): string {
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
