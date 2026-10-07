/**
 * A PromQL parser for converting between the metrics builder and PromQL.
 *
 * It accepts the Prometheus 3 grammar that Snuffle accepts for the queries the builder can describe,
 * plus the constructs a user is likely to paste (offset, `@`, subqueries, vector matching), so a
 * conversion can say which part it drops instead of failing to parse. Quoted UTF-8 metric and label
 * names (`{"http.server.duration", "http.route"="/"}`) are supported because OTel names contain dots.
 */

export type MatchOp = '=' | '!=' | '=~' | '!~'

export interface Matcher {
    label: string
    op: MatchOp
    value: string
}

export interface VectorMatching {
    card: 'one-to-one' | 'many-to-one' | 'one-to-many'
    /** `on (...)` when true, `ignoring (...)` when false. */
    on: boolean
    labels: string[]
    /** Labels listed in `group_left (...)` / `group_right (...)`. */
    include: string[]
}

export type PromExpr =
    | { type: 'number'; value: number }
    | { type: 'string'; value: string }
    | {
          type: 'selector'
          name: string | null
          matchers: Matcher[]
          /** Range in the source form, e.g. `5m`. */
          range?: string
          offset?: string
          at?: string
      }
    | { type: 'subquery'; expr: PromExpr; range: string; step?: string; offset?: string }
    | { type: 'call'; func: string; args: PromExpr[] }
    | {
          type: 'aggregate'
          op: string
          param?: PromExpr
          expr: PromExpr
          grouping?: { without: boolean; labels: string[] }
      }
    | { type: 'binary'; op: string; lhs: PromExpr; rhs: PromExpr; bool?: boolean; matching?: VectorMatching }
    | { type: 'unary'; op: '-' | '+'; expr: PromExpr }
    | { type: 'paren'; expr: PromExpr }
    | { type: 'offset'; expr: PromExpr; offset: string }

export class PromQLParseError extends Error {
    constructor(
        message: string,
        public position: number
    ) {
        super(`${message} at position ${position}`)
        this.name = 'PromQLParseError'
    }
}

type TokenKind = 'number' | 'duration' | 'string' | 'ident' | 'op' | 'eof'

interface Token {
    kind: TokenKind
    value: string
    pos: number
}

export const AGGREGATION_OPS = new Set([
    'sum',
    'avg',
    'count',
    'min',
    'max',
    'stddev',
    'stdvar',
    'topk',
    'bottomk',
    'quantile',
    'count_values',
    'group',
    'limitk',
    'limit_ratio',
    'median',
])
const PARAM_AGGREGATION_OPS = new Set(['topk', 'bottomk', 'quantile', 'count_values', 'limitk', 'limit_ratio'])

const DURATION_RE = /^(\d+(\.\d+)?(ms|s|m|h|d|w|y|i))+/
const NUMBER_RE = /^(0x[0-9a-fA-F]+|(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?)/
// Names may contain colons (recording rules) but do not start with one, so `[5m:30s]` stays a subquery.
const IDENT_RE = /^[a-zA-Z_][a-zA-Z0-9_:]*/
// Longest operators first, so `=~` is not read as `=` then `~`.
const OPERATORS = [
    '==',
    '!=',
    '>=',
    '<=',
    '=~',
    '!~',
    '+',
    '-',
    '*',
    '/',
    '%',
    '^',
    '>',
    '<',
    '=',
    '(',
    ')',
    '{',
    '}',
    '[',
    ']',
    ',',
    ':',
    '@',
]

const STRING_ESCAPES: Record<string, string> = { n: '\n', t: '\t', r: '\r', '\\': '\\', '"': '"', "'": "'", '`': '`' }

function tokenize(input: string): Token[] {
    const tokens: Token[] = []
    let i = 0
    while (i < input.length) {
        const ch = input[i]
        if (/\s/.test(ch)) {
            i++
            continue
        }
        if (ch === '#') {
            while (i < input.length && input[i] !== '\n') {
                i++
            }
            continue
        }
        const rest = input.slice(i)
        if (ch === '"' || ch === "'" || ch === '`') {
            let value = ''
            let j = i + 1
            while (j < input.length && input[j] !== ch) {
                if (input[j] === '\\' && ch !== '`') {
                    const next = input[j + 1]
                    value += next in STRING_ESCAPES ? STRING_ESCAPES[next] : '\\' + next
                    j += 2
                    continue
                }
                value += input[j]
                j++
            }
            if (j >= input.length) {
                throw new PromQLParseError('Unterminated string', i)
            }
            tokens.push({ kind: 'string', value, pos: i })
            i = j + 1
            continue
        }
        const variable = /^\$\{?(__rate_interval|__interval|__range)\}?/.exec(rest)
        if (variable) {
            // Grafana fills these in; they read as "the step", which is what an omitted range means.
            tokens.push({ kind: 'duration', value: `$${variable[1]}`, pos: i })
            i += variable[0].length
            continue
        }
        const duration = DURATION_RE.exec(rest)
        if (duration && !/^[a-zA-Z0-9_]/.test(rest.slice(duration[0].length))) {
            // A bare number followed by a unit is a duration; `5m` is never a number then an identifier.
            tokens.push({ kind: 'duration', value: duration[0], pos: i })
            i += duration[0].length
            continue
        }
        const number = NUMBER_RE.exec(rest)
        if (number && /[0-9.]/.test(ch)) {
            tokens.push({ kind: 'number', value: number[0], pos: i })
            i += number[0].length
            continue
        }
        const ident = IDENT_RE.exec(rest)
        if (ident) {
            let value = ident[0]
            // Lenient: an OTel name typed without quotes (http.server.duration) reads as one identifier.
            const dotted = /^(\.[a-zA-Z0-9_:]+)+/.exec(rest.slice(value.length))
            if (dotted) {
                value += dotted[0]
            }
            tokens.push({ kind: 'ident', value, pos: i })
            i += value.length
            continue
        }
        const op = OPERATORS.find((candidate) => rest.startsWith(candidate))
        if (op) {
            tokens.push({ kind: 'op', value: op, pos: i })
            i += op.length
            continue
        }
        throw new PromQLParseError(`Unexpected character "${ch}"`, i)
    }
    tokens.push({ kind: 'eof', value: '', pos: input.length })
    return tokens
}

// Binary operator precedence, lowest first. `^` is right-associative.
const BINARY_PRECEDENCE: Record<string, number> = {
    or: 1,
    and: 2,
    unless: 2,
    '==': 3,
    '!=': 3,
    '<=': 3,
    '<': 3,
    '>=': 3,
    '>': 3,
    '+': 4,
    '-': 4,
    '*': 5,
    '/': 5,
    '%': 5,
    atan2: 5,
    '^': 6,
}
export const COMPARISON_OPS = new Set(['==', '!=', '<=', '<', '>=', '>'])
export const SET_OPS = new Set(['and', 'or', 'unless'])

export function binaryPrecedence(op: string): number {
    return BINARY_PRECEDENCE[op] ?? 0
}

class Parser {
    private index = 0

    constructor(private tokens: Token[]) {}

    private peek(offset = 0): Token {
        return this.tokens[Math.min(this.index + offset, this.tokens.length - 1)]
    }

    private next(): Token {
        const token = this.peek()
        this.index++
        return token
    }

    private isOp(value: string, offset = 0): boolean {
        const token = this.peek(offset)
        return token.kind === 'op' && token.value === value
    }

    private isKeyword(value: string): boolean {
        const token = this.peek()
        return token.kind === 'ident' && token.value.toLowerCase() === value
    }

    private expectOp(value: string): Token {
        const token = this.next()
        if (token.kind !== 'op' || token.value !== value) {
            throw new PromQLParseError(`Expected "${value}" but found "${token.value || 'end of query'}"`, token.pos)
        }
        return token
    }

    parse(): PromExpr {
        const expr = this.parseBinary(0)
        const token = this.peek()
        if (token.kind !== 'eof') {
            throw new PromQLParseError(`Unexpected "${token.value}"`, token.pos)
        }
        return expr
    }

    private binaryOperator(): string | null {
        const token = this.peek()
        if (token.kind === 'op' && token.value in BINARY_PRECEDENCE) {
            return token.value
        }
        if (token.kind === 'ident' && ['and', 'or', 'unless', 'atan2'].includes(token.value.toLowerCase())) {
            return token.value.toLowerCase()
        }
        return null
    }

    private parseBinary(minPrecedence: number): PromExpr {
        let lhs = this.parseUnary()
        for (;;) {
            const op = this.binaryOperator()
            if (!op || binaryPrecedence(op) < minPrecedence) {
                return lhs
            }
            this.next()
            let bool = false
            if (this.isKeyword('bool')) {
                this.next()
                bool = true
            }
            const matching = this.parseVectorMatching()
            const nextMin = op === '^' ? binaryPrecedence(op) : binaryPrecedence(op) + 1
            const rhs = this.parseBinary(nextMin)
            lhs = {
                type: 'binary',
                op,
                lhs,
                rhs,
                ...(bool ? { bool } : {}),
                ...(matching ? { matching } : {}),
            }
        }
    }

    private parseVectorMatching(): VectorMatching | undefined {
        if (!this.isKeyword('on') && !this.isKeyword('ignoring')) {
            return undefined
        }
        const on = this.next().value.toLowerCase() === 'on'
        const labels = this.parseLabelList()
        const matching: VectorMatching = { card: 'one-to-one', on, labels, include: [] }
        if (this.isKeyword('group_left') || this.isKeyword('group_right')) {
            matching.card = this.next().value.toLowerCase() === 'group_left' ? 'many-to-one' : 'one-to-many'
            if (this.isOp('(')) {
                matching.include = this.parseLabelList()
            }
        }
        return matching
    }

    private parseLabelList(): string[] {
        this.expectOp('(')
        const labels: string[] = []
        while (!this.isOp(')')) {
            const token = this.next()
            if (token.kind !== 'ident' && token.kind !== 'string') {
                throw new PromQLParseError(`Expected a label name but found "${token.value}"`, token.pos)
            }
            labels.push(token.value)
            if (!this.isOp(',')) {
                break
            }
            this.next()
        }
        this.expectOp(')')
        return labels
    }

    private parseUnary(): PromExpr {
        if (this.isOp('-') || this.isOp('+')) {
            const op = this.next().value as '-' | '+'
            // Unary binds tighter than * but looser than ^, as in Prometheus: -2^2 is -(2^2).
            const expr = this.parseBinary(binaryPrecedence('^'))
            if (expr.type === 'number') {
                return { type: 'number', value: op === '-' ? -expr.value : expr.value }
            }
            return { type: 'unary', op, expr }
        }
        return this.parsePostfix(this.parsePrimary())
    }

    private parsePostfix(expr: PromExpr): PromExpr {
        for (;;) {
            if (this.isOp('[')) {
                const open = this.next()
                const range = this.expectDuration()
                if (this.isOp(':')) {
                    this.next()
                    const step = this.peek().kind === 'duration' ? this.expectDuration() : undefined
                    this.expectOp(']')
                    expr = { type: 'subquery', expr, range, ...(step ? { step } : {}) }
                    continue
                }
                this.expectOp(']')
                if (expr.type !== 'selector' || expr.range) {
                    throw new PromQLParseError('A range can only follow a selector', open.pos)
                }
                expr = { ...expr, range }
                continue
            }
            if (this.isKeyword('offset')) {
                this.next()
                const negative = this.isOp('-') ? (this.next(), '-') : ''
                const offset = negative + this.expectDuration()
                expr = expr.type === 'selector' ? { ...expr, offset } : { type: 'offset', expr, offset }
                continue
            }
            if (this.isOp('@')) {
                this.next()
                const token = this.next()
                let at = token.value
                if (token.kind === 'ident') {
                    this.expectOp('(')
                    this.expectOp(')')
                    at += '()'
                }
                if (expr.type === 'selector') {
                    expr = { ...expr, at }
                }
                continue
            }
            return expr
        }
    }

    private expectDuration(): string {
        const token = this.next()
        if (token.kind === 'duration' || token.kind === 'number') {
            return token.value
        }
        throw new PromQLParseError(`Expected a duration but found "${token.value}"`, token.pos)
    }

    private parsePrimary(): PromExpr {
        const token = this.peek()
        if (token.kind === 'number') {
            this.next()
            return { type: 'number', value: Number(token.value) }
        }
        if (token.kind === 'duration') {
            // Durations without units are numbers; with units they are seconds, as in PromQL arithmetic.
            this.next()
            return { type: 'number', value: durationToSeconds(token.value) }
        }
        if (token.kind === 'string') {
            this.next()
            return { type: 'string', value: token.value }
        }
        if (this.isOp('(')) {
            this.next()
            const expr = this.parseBinary(0)
            this.expectOp(')')
            return { type: 'paren', expr }
        }
        if (this.isOp('{')) {
            return this.parseSelector(null)
        }
        if (token.kind === 'ident') {
            const lower = token.value.toLowerCase()
            if (lower === 'inf' || lower === 'nan') {
                this.next()
                return { type: 'number', value: lower === 'inf' ? Infinity : NaN }
            }
            if (AGGREGATION_OPS.has(lower) && (this.isOp('(', 1) || this.isGroupingKeyword(1))) {
                return this.parseAggregate()
            }
            if (this.isOp('(', 1)) {
                return this.parseCall()
            }
            this.next()
            return this.parseSelector(token.value)
        }
        throw new PromQLParseError(`Unexpected "${token.value || 'end of query'}"`, token.pos)
    }

    private isGroupingKeyword(offset: number): boolean {
        const token = this.peek(offset)
        return token.kind === 'ident' && ['by', 'without'].includes(token.value.toLowerCase())
    }

    private parseGrouping(): { without: boolean; labels: string[] } {
        const without = this.next().value.toLowerCase() === 'without'
        return { without, labels: this.parseLabelList() }
    }

    private parseAggregate(): PromExpr {
        const op = this.next().value.toLowerCase()
        let grouping = this.isGroupingKeyword(0) ? this.parseGrouping() : undefined
        this.expectOp('(')
        const args: PromExpr[] = []
        while (!this.isOp(')')) {
            args.push(this.parseBinary(0))
            if (!this.isOp(',')) {
                break
            }
            this.next()
        }
        const close = this.expectOp(')')
        if (!grouping && this.isGroupingKeyword(0)) {
            grouping = this.parseGrouping()
        }
        const hasParam = PARAM_AGGREGATION_OPS.has(op)
        if (args.length !== (hasParam ? 2 : 1) && op !== 'median') {
            throw new PromQLParseError(`${op} expects ${hasParam ? 2 : 1} argument(s)`, close.pos)
        }
        return {
            type: 'aggregate',
            op,
            ...(hasParam ? { param: args[0] } : {}),
            expr: hasParam ? args[1] : args[0],
            ...(grouping ? { grouping } : {}),
        }
    }

    private parseCall(): PromExpr {
        const func = this.next().value
        this.expectOp('(')
        const args: PromExpr[] = []
        while (!this.isOp(')')) {
            args.push(this.parseBinary(0))
            if (!this.isOp(',')) {
                break
            }
            this.next()
        }
        this.expectOp(')')
        return { type: 'call', func, args }
    }

    private parseSelector(name: string | null): PromExpr {
        const matchers: Matcher[] = []
        if (this.isOp('{')) {
            this.next()
            while (!this.isOp('}')) {
                const labelToken = this.next()
                if (labelToken.kind !== 'ident' && labelToken.kind !== 'string') {
                    throw new PromQLParseError(`Expected a label name but found "${labelToken.value}"`, labelToken.pos)
                }
                // A lone quoted string inside braces is the Prometheus 3 form of the metric name.
                if (labelToken.kind === 'string' && (this.isOp(',') || this.isOp('}'))) {
                    if (name !== null) {
                        throw new PromQLParseError('A selector can only have one metric name', labelToken.pos)
                    }
                    name = labelToken.value
                } else {
                    const opToken = this.next()
                    if (opToken.kind !== 'op' || !['=', '!=', '=~', '!~'].includes(opToken.value)) {
                        throw new PromQLParseError(`Expected a label matcher but found "${opToken.value}"`, opToken.pos)
                    }
                    const valueToken = this.next()
                    if (valueToken.kind !== 'string') {
                        throw new PromQLParseError('A label value must be a quoted string', valueToken.pos)
                    }
                    matchers.push({ label: labelToken.value, op: opToken.value as MatchOp, value: valueToken.value })
                }
                if (!this.isOp(',')) {
                    break
                }
                this.next()
            }
            this.expectOp('}')
        }
        if (name === null && matchers.length === 0) {
            throw new PromQLParseError('A selector needs a metric name or a label matcher', this.peek().pos)
        }
        // `{__name__="x"}` and `x{}` are the same selector; keep one form so they compare equal.
        const nameMatcher = name === null ? matchers.findIndex((m) => m.label === '__name__' && m.op === '=') : -1
        if (nameMatcher >= 0) {
            name = matchers[nameMatcher].value
            matchers.splice(nameMatcher, 1)
        }
        return { type: 'selector', name, matchers }
    }
}

const DURATION_UNITS: Record<string, number> = {
    ms: 0.001,
    s: 1,
    m: 60,
    h: 3600,
    d: 86400,
    w: 604800,
    y: 31536000,
}

/** Seconds in a PromQL duration such as `1h30m`. Step units (`4i`) and unitless values are read as seconds. */
export function durationToSeconds(duration: string): number {
    let total = 0
    let matched = false
    for (const match of duration.matchAll(/(\d+(?:\.\d+)?)(ms|s|m|h|d|w|y|i)?/g)) {
        if (!match[0]) {
            continue
        }
        matched = true
        total += Number(match[1]) * (match[2] && match[2] !== 'i' ? DURATION_UNITS[match[2]] : 1)
    }
    return matched ? total : NaN
}

export function parsePromQL(input: string): PromExpr {
    return new Parser(tokenize(input)).parse()
}

/** Removes redundant parentheses so structural matching does not have to look through them. */
export function unwrapParens(expr: PromExpr): PromExpr {
    while (expr.type === 'paren') {
        expr = expr.expr
    }
    return expr
}
