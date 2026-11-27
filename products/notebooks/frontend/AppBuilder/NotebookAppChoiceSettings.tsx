import { LemonInput, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import type { NotebookBlockNode } from 'lib/components/MarkdownNotebook/types'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import type { NotebookVariable } from 'scenes/notebooks/Notebook/notebookVariables'

import type { NotebookAppBlockApi } from '../generated/api.schemas'
import { sqlChoiceSource } from './notebookAppChoices'
import { appCellTitle } from './notebookAppLayout'

type ChoiceSettingsProps = {
    cells: NotebookBlockNode[]
    block: NotebookAppBlockApi
    onChange: (patch: Partial<NotebookAppBlockApi>) => void
}

export function NotebookAppChoiceSettings({
    variableType,
    ...props
}: ChoiceSettingsProps & { variableType?: NotebookVariable['type'] }): JSX.Element | null {
    const { block, onChange } = props
    if (block.input_kind === 'query_select') {
        return <QueryChoiceSettings {...props} />
    }
    if (block.input_kind !== 'select') {
        return null
    }
    return (
        <>
            <LemonLabel>Options (one per line)</LemonLabel>
            <LemonTextArea
                value={(block.options ?? []).join('\n')}
                onChange={(text) => onChange({ options: text.split('\n') })}
                aria-label="Dropdown options"
            />
            {variableType !== 'list' && (
                <span className="text-xs text-secondary">
                    To allow multiple selections, choose List of text in the notebook variables.
                </span>
            )}
        </>
    )
}

function QueryChoiceSettings({ cells, block, onChange }: ChoiceSettingsProps): JSX.Element {
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
