import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import type { NotebookBlockNode } from 'lib/components/MarkdownNotebook/types'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import type { NotebookAppBlockApi } from '../generated/api.schemas'
import { sqlChoiceSource } from './notebookAppChoices'
import { appCellTitle } from './notebookAppLayout'

export function NotebookAppChoiceSettings({
    cells,
    block,
    onChange,
}: {
    cells: NotebookBlockNode[]
    block: NotebookAppBlockApi
    onChange: (patch: Partial<NotebookAppBlockApi>) => void
}): JSX.Element {
    const sources = cells.filter((cell) => sqlChoiceSource(cell))
    const columnsFor = (id?: string): string[] => {
        const result = sqlChoiceSource(sources.find((cell) => cell.id === id))?.result
        return result && typeof result === 'object' && !Array.isArray(result) && Array.isArray(result.columns)
            ? result.columns.filter((name): name is string => typeof name === 'string')
            : []
    }
    const columns = columnsFor(block.node_id)
    return (
        <>
            <LemonLabel>Options query</LemonLabel>
            <LemonSelect
                fullWidth
                aria-label="Options query"
                value={block.node_id || undefined}
                placeholder="Choose a SQL cell"
                options={sources.map((cell) => ({ value: cell.id, label: appCellTitle(cell) }))}
                onChange={(node_id) => onChange({ node_id, option_column: columnsFor(node_id)[0] ?? '' })}
            />
            <LemonLabel>Options column</LemonLabel>
            {columns.length ? (
                <LemonSelect
                    fullWidth
                    aria-label="Options column"
                    value={block.option_column}
                    options={columns.map((value) => ({ value, label: value }))}
                    onChange={(option_column) => onChange({ option_column })}
                />
            ) : (
                <LemonInput
                    aria-label="Options column"
                    value={block.option_column ?? ''}
                    onChange={(option_column) => onChange({ option_column })}
                />
            )}
            <p className="text-xs text-secondary">
                Reference another input in the query to update these choices when that input changes.
            </p>
        </>
    )
}
