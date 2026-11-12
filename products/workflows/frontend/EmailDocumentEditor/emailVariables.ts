export const EMAIL_LIQUID_OUTPUT = /\{\{([\s\S]*?)\}\}/

export interface ParsedLiquidOutput {
    expression: string
    fallback: string
}

/** Splits `name | default: 'x'` so a chip can show and edit its fallback. Other filters stay part of the expression. */
export function parseLiquidOutput(inner: string): ParsedLiquidOutput {
    const match = inner.match(/^([\s\S]*?)\s*\|\s*default:\s*(['"])((?:\\.|(?!\2).)*)\2\s*$/)
    if (!match) {
        return { expression: inner.trim(), fallback: '' }
    }
    return { expression: match[1].trim(), fallback: match[3].replace(/\\(['"\\])/g, '$1') }
}

/** The path a Liquid expression reads, in dotted form: `person.properties['a b'] | upcase` becomes `person.properties.a b`. */
export function variablePath(expression: string): string {
    return expression
        .split('|')[0]
        .trim()
        .replace(/\[\s*['"]([^'"]*)['"]\s*\]/g, '.$1')
}

export interface EmailVariableOption {
    label: string
    expression: string
    group: string
}

export interface EmailVariableContext {
    transactional: boolean
    /** Null until the definitions have loaded, so nothing is flagged while they're on their way. */
    personProperties: string[] | null
    extra: string[]
}

const ALWAYS_KNOWN = new Set(['unsubscribe_url', 'unsubscribe_url_one_click'])
const OPEN_ROOTS = ['event', 'groups', 'project', 'source', 'inputs', 'person']

/** The reason a variable won't resolve when the email is sent, or null when it looks fine. */
export function undefinedVariableReason(
    expression: string,
    fallback: string,
    context: EmailVariableContext
): string | null {
    const path = variablePath(expression)
    if (fallback || ALWAYS_KNOWN.has(path) || expression.includes('default:')) {
        return null
    }
    const root = path.split('.')[0]
    if (context.transactional) {
        return root === 'variables' ? null : `Transactional emails only read variables, so ${path} will be empty.`
    }
    if (root === 'variables') {
        return `${path} only exists in transactional emails, so it will be empty here.`
    }
    if (path.startsWith('person.properties.')) {
        const property = path.slice('person.properties.'.length)
        if (context.personProperties && !context.personProperties.includes(property)) {
            return `No person has the property ${property} yet, so it will be empty unless you add a fallback.`
        }
        return null
    }
    if (OPEN_ROOTS.includes(root) || context.extra.includes(root)) {
        return null
    }
    return `${path} isn't a variable this email can read, so it will be empty.`
}

export function variableOptions(mergeTags: Record<string, any> | undefined | null): EmailVariableOption[] {
    const options = Object.values(mergeTags ?? {}).flatMap((tag: any) => {
        const match = typeof tag?.value === 'string' ? tag.value.match(EMAIL_LIQUID_OUTPUT) : null
        if (!match) {
            return []
        }
        const expression = match[1].trim()
        const group = expression.startsWith('unsubscribe')
            ? 'Unsubscribe'
            : expression.startsWith('variables.')
              ? 'Variables'
              : 'Person properties'
        return [{ label: String(tag.name ?? expression), expression, group }]
    })
    // Properties people set come before the many that SDKs add on their own, like $initial_utm_source.
    return [
        ...options.filter((option) => !option.label.startsWith('$')),
        ...options.filter((option) => option.label.startsWith('$')),
    ]
}
