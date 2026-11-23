import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import type { NotebookBlockNode } from 'lib/components/MarkdownNotebook/types'
import type { NotebookVariable } from 'scenes/notebooks/Notebook/notebookVariables'

import type { NotebookAppBlockApi } from '../generated/api.schemas'
import { appCellTitle } from './notebookAppLayout'

export function NotebookAppPalette({
    cells,
    variables,
    onAdd,
    onAddCell,
    onUseNotebook,
}: {
    cells: NotebookBlockNode[]
    variables: NotebookVariable[]
    onAdd: (kind: NotebookAppBlockApi['kind'], patch?: Partial<NotebookAppBlockApi>) => void
    onAddCell: (id: string) => void
    onUseNotebook: () => void
}): JSX.Element {
    const [search, setSearch] = useState('')
    const matchingCells = cells.filter((cell) => appCellTitle(cell).toLowerCase().includes(search.toLowerCase()))
    return (
        <aside
            className="NotebookAppBuilder__palette border rounded bg-surface-primary p-3 flex flex-col gap-3"
            aria-label="App components"
        >
            <h3 className="m-0">Components</h3>
            <div className="flex flex-wrap gap-2">
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconPlus />}
                    onClick={() => onAdd('text', { text: '## Section title\n\nAdd context for your readers.' })}
                    data-attr="notebook-app-add-text"
                >
                    Text
                </LemonButton>
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => onAdd('divider')}
                    data-attr="notebook-app-add-divider"
                >
                    Divider
                </LemonButton>
            </div>
            <div className="border-t pt-3">
                <h4>Notebook inputs</h4>
                {variables.length ? (
                    variables.map((variable) => (
                        <LemonButton
                            key={variable.name}
                            size="small"
                            fullWidth
                            icon={<IconPlus />}
                            onClick={() =>
                                onAdd('input', { variable: variable.name, title: variable.name, input_kind: 'auto' })
                            }
                            data-attr="notebook-app-add-input"
                        >
                            <span className="truncate">{variable.name}</span>
                        </LemonButton>
                    ))
                ) : (
                    <p className="text-xs text-secondary">
                        Add variables in the notebook to create text, number, date, checkbox, dropdown, and slider
                        inputs.
                    </p>
                )}
            </div>
            <div className="border-t pt-3 flex flex-col gap-2">
                <h4 className="m-0">Notebook cells</h4>
                <LemonInput type="search" size="small" placeholder="Find a cell" value={search} onChange={setSearch} />
                <p className="text-xs text-secondary m-0">
                    Charts, tables, images, and widgets stay linked to their source cells.
                </p>
                <div className="max-h-96 overflow-y-auto">
                    {matchingCells.map((cell) => (
                        <LemonButton
                            key={cell.id}
                            size="small"
                            fullWidth
                            icon={<IconPlus />}
                            onClick={() => onAddCell(cell.id)}
                            data-attr="notebook-app-add-cell"
                        >
                            <span className="truncate">{appCellTitle(cell)}</span>
                        </LemonButton>
                    ))}
                    {!matchingCells.length && (
                        <p className="text-xs text-secondary">No matching cells. Add content in the notebook first.</p>
                    )}
                </div>
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={onUseNotebook}
                    disabledReason={!cells.length ? 'Add notebook cells first' : undefined}
                    data-attr="notebook-app-use-notebook"
                >
                    Use notebook layout
                </LemonButton>
            </div>
        </aside>
    )
}
