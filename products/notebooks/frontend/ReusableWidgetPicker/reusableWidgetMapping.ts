import type { NotebookFrameNodeSummary } from 'scenes/notebooks/Nodes/notebookNodeContent'

import { escapeHogQLString } from '~/queries/utils'

import type { WidgetInputContractColumnApi } from '../generated/api.schemas'

export function widgetInputMatches(columns: WidgetInputContractColumnApi[], frame: NotebookFrameNodeSummary): boolean {
    return (
        columns.length === frame.columns.length &&
        columns.every(
            (column, index) => column.name === frame.columns[index][0] && column.type === frame.columns[index][1]
        )
    )
}

export function defaultColumnMapping(
    columns: WidgetInputContractColumnApi[],
    frame: NotebookFrameNodeSummary | undefined
): Record<string, string> {
    return Object.fromEntries(
        columns.map(({ name, type }) => [
            name,
            frame?.columns.some(([source, sourceType]) => source === name && sourceType === type) ? name : '',
        ])
    )
}

export function columnMappingHog(columns: WidgetInputContractColumnApi[], mapping: Record<string, string>): string {
    if (!columns.length) {
        return 'return rows'
    }
    const fields = columns
        .map(({ name }) => `${escapeHogQLString(name)}: row[${escapeHogQLString(mapping[name] ?? name)}]`)
        .join(', ')
    return `let mapped := [];\nfor (let row in rows) {\n    mapped := arrayPushBack(mapped, {${fields}});\n}\nreturn mapped`
}

export function widgetMappingIssues(
    columns: WidgetInputContractColumnApi[],
    frame: NotebookFrameNodeSummary
): string[] {
    const issues = columns.flatMap(({ name, type }) => {
        const source = frame.columns.find(([sourceName]) => sourceName === name)
        return !source
            ? [`Missing column: ${name}`]
            : source[1] !== type
              ? [`${name}: expected ${type}, found ${source[1]}`]
              : []
    })
    if (!issues.length && !widgetInputMatches(columns, frame)) {
        issues.push('The columns need to be reordered or extra columns removed.')
    }
    return issues
}
