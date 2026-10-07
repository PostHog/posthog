import { type Matcher, type PromExpr, binaryPrecedence } from './promqlParser'

const LEGACY_METRIC_NAME = /^[a-zA-Z_:][a-zA-Z0-9_:]*$/
const LEGACY_LABEL_NAME = /^[a-zA-Z_][a-zA-Z0-9_]*$/

export function quotePromString(value: string): string {
    return JSON.stringify(value)
}

/** A label name as PromQL needs it: bare when it is a legacy name, quoted (Prometheus 3) otherwise. */
export function printLabelName(label: string): string {
    return LEGACY_LABEL_NAME.test(label) ? label : quotePromString(label)
}

function printMatcher(matcher: Matcher): string {
    return `${printLabelName(matcher.label)}${matcher.op}${quotePromString(matcher.value)}`
}

function printSelector(expr: Extract<PromExpr, { type: 'selector' }>): string {
    const matchers = expr.matchers.map(printMatcher)
    let out: string
    if (expr.name !== null && LEGACY_METRIC_NAME.test(expr.name)) {
        out = expr.name + (matchers.length ? `{${matchers.join(', ')}}` : '')
    } else if (expr.name !== null) {
        out = `{${[quotePromString(expr.name), ...matchers].join(', ')}}`
    } else {
        out = `{${matchers.join(', ')}}`
    }
    if (expr.range) {
        out += `[${expr.range}]`
    }
    if (expr.offset) {
        out += ` offset ${expr.offset}`
    }
    if (expr.at) {
        out += ` @ ${expr.at}`
    }
    return out
}

function printNumber(value: number): string {
    if (Number.isNaN(value)) {
        return 'NaN'
    }
    if (!Number.isFinite(value)) {
        return value > 0 ? 'Inf' : '-Inf'
    }
    return String(value)
}

function printLabelList(labels: string[]): string {
    return `(${labels.map(printLabelName).join(', ')})`
}

// Precedence of an expression as an operand, so the printer adds only the parentheses it needs.
function precedenceOf(expr: PromExpr): number {
    if (expr.type === 'binary') {
        return binaryPrecedence(expr.op)
    }
    if (expr.type === 'unary') {
        return binaryPrecedence('^') - 0.5
    }
    if (expr.type === 'number' && expr.value < 0) {
        return binaryPrecedence('^') - 0.5
    }
    return Infinity
}

function printOperand(expr: PromExpr, parentPrecedence: number, right: boolean, parentOp: string): string {
    const precedence = precedenceOf(expr)
    const rightAssociative = parentOp === '^'
    const needsParens =
        precedence < parentPrecedence ||
        (precedence === parentPrecedence && (rightAssociative ? !right : right) && expr.type === 'binary')
    const printed = printPromQL(expr)
    return needsParens ? `(${printed})` : printed
}

export function printPromQL(expr: PromExpr): string {
    switch (expr.type) {
        case 'number':
            return printNumber(expr.value)
        case 'string':
            return quotePromString(expr.value)
        case 'selector':
            return printSelector(expr)
        case 'paren':
            return `(${printPromQL(expr.expr)})`
        case 'unary':
            return `${expr.op}${printOperand(expr.expr, binaryPrecedence('^'), false, '')}`
        case 'offset':
            return `${printOperand(expr.expr, Infinity, false, '')} offset ${expr.offset}`
        case 'subquery':
            return `${printOperand(expr.expr, Infinity, false, '')}[${expr.range}:${expr.step ?? ''}]${
                expr.offset ? ` offset ${expr.offset}` : ''
            }${expr.at ? ` @ ${expr.at}` : ''}`
        case 'call':
            return `${expr.func}(${expr.args.map(printPromQL).join(', ')})`
        case 'aggregate': {
            const grouping = expr.grouping
                ? ` ${expr.grouping.without ? 'without' : 'by'} ${printLabelList(expr.grouping.labels)}`
                : ''
            const args = [...(expr.param ? [printPromQL(expr.param)] : []), printPromQL(expr.expr)]
            return `${expr.op}${grouping}${grouping ? ' ' : ''}(${args.join(', ')})`
        }
        case 'binary': {
            const precedence = binaryPrecedence(expr.op)
            let modifiers = expr.bool ? ' bool' : ''
            if (expr.matching) {
                modifiers += ` ${expr.matching.on ? 'on' : 'ignoring'}${printLabelList(expr.matching.labels)}`
                if (expr.matching.card !== 'one-to-one') {
                    modifiers += ` ${expr.matching.card === 'many-to-one' ? 'group_left' : 'group_right'}`
                    if (expr.matching.include.length) {
                        modifiers += printLabelList(expr.matching.include)
                    }
                }
            }
            return `${printOperand(expr.lhs, precedence, false, expr.op)} ${expr.op}${modifiers} ${printOperand(
                expr.rhs,
                precedence,
                true,
                expr.op
            )}`
        }
    }
}
