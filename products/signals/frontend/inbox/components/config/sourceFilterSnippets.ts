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

/**
 * Append a snippet to the expression. After a finished condition it is joined with AND, so picking
 * several snippets in a row builds a valid expression. The cursor lands where the value goes.
 */
export function appendSnippet(
    expression: string,
    appended: SourceFilterSnippet
): { expression: string; cursor: number } {
    const before = expression.trimEnd()
    const joiner = !before || before.endsWith('(') ? '' : ENDS_OPEN.test(before) ? ' ' : ' AND '
    const head = `${before}${joiner}`
    return { expression: `${head}${appended.text}`, cursor: head.length + appended.cursorOffset }
}
