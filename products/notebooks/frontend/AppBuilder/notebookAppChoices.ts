import type { NotebookBlockNode } from 'lib/components/MarkdownNotebook/types'
import { getSqlV2PropsFromQueryProp } from 'scenes/notebooks/Notebook/markdownNotebookV2'
import { MAX_NOTEBOOK_VARIABLE_VALUE_CHARS } from 'scenes/notebooks/Notebook/notebookVariables'

export type AppChoices = { values: string[]; partial: boolean }

export function queryChoices(columns: unknown, rows: unknown, column: string, partial: boolean): AppChoices | null {
    const index = Array.isArray(columns) ? columns.indexOf(column) : -1
    if (index < 0 || !Array.isArray(rows)) {
        return null
    }
    const choices = new Set<string>()
    for (const row of rows) {
        const raw = Array.isArray(row) ? row[index] : undefined
        if (typeof raw !== 'string' && typeof raw !== 'number' && typeof raw !== 'boolean') {
            continue
        }
        const value = String(raw)
        if (!value || Array.from(value).length > MAX_NOTEBOOK_VARIABLE_VALUE_CHARS) {
            continue
        }
        choices.add(value)
        if (choices.size > 100) {
            return { values: [...choices].slice(0, 100), partial: true }
        }
    }
    return { values: [...choices], partial }
}

export function sqlChoiceSource(cell?: NotebookBlockNode): ReturnType<typeof getSqlV2PropsFromQueryProp> {
    if (cell?.type !== 'component' || cell.tagName !== 'SQLV2') {
        return null
    }
    const attributes = { ...cell.props, ...getSqlV2PropsFromQueryProp(cell.props) }
    return attributes.connectionId || attributes.sendRawQuery ? null : attributes
}

export function draftChoices(cell: NotebookBlockNode | undefined, column: string): AppChoices | null {
    const result = sqlChoiceSource(cell)?.result
    return result && typeof result === 'object' && !Array.isArray(result)
        ? queryChoices(result.columns, result.first_page, column, !!result.has_more)
        : null
}
