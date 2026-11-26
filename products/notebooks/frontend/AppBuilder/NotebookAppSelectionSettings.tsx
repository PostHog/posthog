import { LemonCheckbox, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import type { NotebookComponentBlockNode } from 'lib/components/MarkdownNotebook/types'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { getSqlV2PropsFromQueryProp } from 'scenes/notebooks/Notebook/markdownNotebookV2'

import type { NotebookAppBlockApi, NotebookAppLayoutApi } from '../generated/api.schemas'

function resultColumnNames(cell: NotebookComponentBlockNode): string[] {
    const result = { ...cell.props, ...getSqlV2PropsFromQueryProp(cell.props) }.result
    return result && typeof result === 'object' && !Array.isArray(result) && Array.isArray(result.columns)
        ? result.columns.filter((name): name is string => typeof name === 'string')
        : []
}

export function NotebookAppSelectionSettings({
    cell,
    block,
    layout,
    onChange,
}: {
    cell: NotebookComponentBlockNode
    block: NotebookAppBlockApi
    layout: NotebookAppLayoutApi
    onChange: (selection: NotebookAppBlockApi['selection']) => void
}): JSX.Element {
    const selection = block.selection
    const inputs = layout.blocks.filter((item) => item.kind === 'input' && item.variable)
    const columns = resultColumnNames(cell)
    return (
        <>
            <LemonCheckbox
                label="Set an input on selection"
                checked={!!selection}
                disabledReason={!inputs.length && !selection ? 'Add an input to the app first.' : undefined}
                onChange={(checked) =>
                    onChange(
                        checked
                            ? { column: columns[0] ?? '', variable: inputs[0]?.variable ?? '', condition_bytecode: [] }
                            : null
                    )
                }
            />
            {selection && (
                <>
                    <LemonLabel>Result column</LemonLabel>
                    {columns.length ? (
                        <LemonSelect
                            fullWidth
                            value={selection.column}
                            aria-label="Result column"
                            options={columns.map((name) => ({ value: name, label: name }))}
                            onChange={(column) => onChange({ ...selection, column })}
                        />
                    ) : (
                        <LemonInput
                            value={selection.column}
                            aria-label="Result column"
                            onChange={(column) => onChange({ ...selection, column })}
                        />
                    )}
                    <LemonLabel>Set input</LemonLabel>
                    <LemonSelect
                        fullWidth
                        value={selection.variable}
                        aria-label="Set input"
                        options={inputs.map((item) => ({ value: item.variable!, label: item.title || item.variable! }))}
                        onChange={(variable) => onChange({ ...selection, variable })}
                    />
                    <LemonLabel>Open tab</LemonLabel>
                    <LemonSelect
                        fullWidth
                        value={selection.tab_id || ''}
                        aria-label="Open tab"
                        options={[
                            { value: '', label: 'Stay on this tab' },
                            ...layout.tabs.map((tab) => ({ value: tab.id, label: tab.title })),
                        ]}
                        onChange={(tab_id) => onChange({ ...selection, tab_id })}
                    />
                    <LemonLabel>Only when</LemonLabel>
                    <LemonInput
                        value={selection.condition ?? ''}
                        aria-label="Hog selection condition"
                        placeholder="Optional Hog expression"
                        maxLength={1200}
                        onChange={(condition) => onChange({ ...selection, condition })}
                    />
                    <p className="text-xs text-secondary">
                        Use <code>value</code> for the selected value, <code>row</code> for the result, and{' '}
                        <code>inputs</code> for the current app inputs. On a line or bar chart, select the x-axis
                        column.
                    </p>
                </>
            )}
        </>
    )
}
