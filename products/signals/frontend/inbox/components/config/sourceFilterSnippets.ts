import type { SourceFilterCatalogFieldApi } from 'products/signals/frontend/generated/api.schemas'

const CURSOR = '|'

export interface SourceFilterSnippet {
    /** The text inserted into the expression. */
    text: string
    /** Where the cursor lands inside `text`, so the person types the value next. */
    cursorOffset: number
}

function snippet(template: string): SourceFilterSnippet {
    const cursorOffset = template.indexOf(CURSOR)
    return cursorOffset === -1
        ? { text: template, cursorOffset: template.length }
        : { text: template.replace(CURSOR, ''), cursorOffset }
}

// Only forms `FilterExpression` in products/signals/backend/filter_expression.py accepts, so an
// inserted snippet never fails to save for its shape alone.
export function snippetsForField(field: Pick<SourceFilterCatalogFieldApi, 'name' | 'type'>): SourceFilterSnippet[] {
    const { name, type } = field
    switch (type) {
        case 'string':
            return [
                `${name} = '|'`,
                `${name} != '|'`,
                `${name} IN ('|')`,
                `${name} IS NULL`,
                `${name} IS NOT NULL`,
            ].map(snippet)
        case 'integer':
        case 'number':
            return [`${name} = |`, `${name} IN (|)`, `${name} < |`, `${name} > |`].map(snippet)
        case 'boolean':
            return [`${name} = true`, `${name} = false`].map(snippet)
        case 'array<string>':
            return [`has(${name}, '|')`, `NOT has(${name}, '|')`].map(snippet)
        default:
            return [`${name} IS NULL`, `${name} IS NOT NULL`].map(snippet)
    }
}

const ENDS_OPEN = /(\bAND|\bOR|\bNOT|\()\s*$/i

/** Whether the expression has an OR outside any brackets or quoted strings. */
function hasTopLevelOr(expression: string): boolean {
    let depth = 0
    let quoted = false
    for (let i = 0; i < expression.length; i++) {
        const char = expression[i]
        if (char === "'" && expression[i - 1] !== '\\') {
            quoted = !quoted
        } else if (!quoted && char === '(') {
            depth++
        } else if (!quoted && char === ')') {
            depth--
        } else if (
            !quoted &&
            depth === 0 &&
            /^OR\b/i.test(expression.slice(i)) &&
            /(^|[\s)])$/.test(expression.slice(0, i))
        ) {
            return true
        }
    }
    return false
}

/**
 * Append a snippet to the expression. After a finished condition it is joined with AND, so picking
 * several snippets in a row builds a valid expression. AND binds tighter than OR, so a finished
 * expression with a top-level OR is bracketed first, and the new condition applies to all of it.
 * The cursor lands where the value goes.
 */
export function appendSnippet(
    expression: string,
    appended: SourceFilterSnippet
): { expression: string; cursor: number } {
    const before = expression.trimEnd()
    let head: string
    if (!before) {
        head = ''
    } else if (ENDS_OPEN.test(before)) {
        head = before.endsWith('(') ? before : `${before} `
    } else {
        head = `${hasTopLevelOr(before) ? `(${before})` : before} AND `
    }
    return { expression: `${head}${appended.text}`, cursor: head.length + appended.cursorOffset }
}
