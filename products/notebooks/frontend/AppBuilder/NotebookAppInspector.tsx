import { LemonButton, LemonCheckbox, LemonInput, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import type { NotebookBlockNode } from 'lib/components/MarkdownNotebook/types'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import type { NotebookVariable } from 'scenes/notebooks/Notebook/notebookVariables'

import type { NotebookAppBlockApi, NotebookAppLayoutApi } from '../generated/api.schemas'
import { appCellTitle } from './notebookAppLayout'

export function NotebookAppInspector({
    layout,
    block,
    cells,
    variables,
    onLayout,
    onBlock,
    onClose,
    onSource,
}: {
    layout: NotebookAppLayoutApi
    block: NotebookAppBlockApi | null
    cells: NotebookBlockNode[]
    variables: NotebookVariable[]
    onLayout: (layout: NotebookAppLayoutApi) => void
    onBlock: (id: string, patch: Partial<NotebookAppBlockApi>) => void
    onClose: () => void
    onSource: (id: string) => void
}): JSX.Element {
    return (
        <aside
            className="NotebookAppBuilder__inspector border rounded bg-surface-primary p-3 flex flex-col gap-3"
            aria-label={block ? 'Component settings' : 'App settings'}
        >
            <div className="flex items-center justify-between">
                <h3 className="m-0">{block ? 'Component settings' : 'App settings'}</h3>
                {block && (
                    <LemonButton size="xsmall" onClick={onClose}>
                        Done
                    </LemonButton>
                )}
            </div>
            {!block ? (
                <>
                    <LemonLabel>App title</LemonLabel>
                    <LemonInput
                        value={layout.title ?? ''}
                        placeholder="Notebook title"
                        onChange={(title) => onLayout({ ...layout, title })}
                        aria-label="App title"
                    />
                    <LemonLabel>Description</LemonLabel>
                    <LemonTextArea
                        value={layout.description ?? ''}
                        onChange={(description) => onLayout({ ...layout, description })}
                        maxLength={2000}
                        placeholder="What can people learn from this app?"
                        aria-label="App description"
                    />
                    <LemonCheckbox
                        label="Use full width"
                        checked={!!layout.full_width}
                        onChange={(full_width) => onLayout({ ...layout, full_width })}
                    />
                    <p className="text-xs text-secondary">
                        Publishing saves the layout, source cells, and default inputs. People need access to this
                        notebook to open the app.
                    </p>
                </>
            ) : (
                <>
                    <LemonLabel>Title</LemonLabel>
                    <LemonInput
                        value={block.title ?? ''}
                        maxLength={256}
                        onChange={(title) => onBlock(block.id, { title })}
                        aria-label="Component title"
                    />
                    <LemonLabel>Width</LemonLabel>
                    <LemonSelect
                        fullWidth
                        value={block.width ?? 12}
                        options={[
                            { value: 3, label: 'Quarter' },
                            { value: 4, label: 'Third' },
                            { value: 6, label: 'Half' },
                            { value: 8, label: 'Two thirds' },
                            { value: 9, label: 'Three quarters' },
                            { value: 12, label: 'Full' },
                        ]}
                        onChange={(width) => onBlock(block.id, { width })}
                    />
                    <LemonLabel>Tab</LemonLabel>
                    <LemonSelect
                        fullWidth
                        value={block.tab_id}
                        options={layout.tabs.map((tab) => ({ value: tab.id, label: tab.title }))}
                        onChange={(tab_id) => onBlock(block.id, { tab_id })}
                    />
                    {block.kind === 'text' && (
                        <>
                            <LemonLabel>Text (Markdown)</LemonLabel>
                            <LemonTextArea
                                value={block.text ?? ''}
                                onChange={(text) => onBlock(block.id, { text })}
                                maxLength={20000}
                                minRows={8}
                                aria-label="Component text"
                            />
                        </>
                    )}
                    {block.kind === 'cell' && (
                        <>
                            <LemonLabel>Source cell</LemonLabel>
                            <LemonSelect
                                fullWidth
                                value={block.node_id}
                                options={cells
                                    .filter(
                                        (cell) =>
                                            cell.id.startsWith('phb-') ||
                                            (cell.type === 'component' && !!cell.props.nodeId)
                                    )
                                    .map((cell) => ({ value: cell.id, label: appCellTitle(cell) }))}
                                onChange={(node_id) => onBlock(block.id, { node_id })}
                            />
                            <LemonLabel>Display</LemonLabel>
                            <LemonSelect
                                fullWidth
                                value={block.display ?? 'output'}
                                options={[
                                    { value: 'output', label: 'Output' },
                                    { value: 'source', label: 'Source' },
                                    { value: 'both', label: 'Source and output' },
                                ]}
                                onChange={(display) => onBlock(block.id, { display })}
                            />
                            <LemonButton size="small" type="secondary" onClick={() => onSource(block.node_id || '')}>
                                Open source cell
                            </LemonButton>
                        </>
                    )}
                    {block.kind === 'input' && (
                        <>
                            <LemonLabel>Notebook variable</LemonLabel>
                            <LemonSelect
                                fullWidth
                                value={block.variable}
                                options={variables.map((variable) => ({ value: variable.name, label: variable.name }))}
                                onChange={(variable) => onBlock(block.id, { variable })}
                            />
                            <LemonLabel>Control</LemonLabel>
                            <LemonSelect
                                fullWidth
                                value={block.input_kind ?? 'auto'}
                                options={[
                                    { value: 'auto', label: 'Match variable type' },
                                    { value: 'select', label: 'Dropdown' },
                                    {
                                        value: 'slider',
                                        label: 'Slider',
                                        disabledReason:
                                            variables.find((variable) => variable.name === block.variable)?.type !==
                                            'number'
                                                ? 'Select a number variable first'
                                                : undefined,
                                    },
                                ]}
                                onChange={(input_kind) => onBlock(block.id, { input_kind })}
                            />
                            {block.input_kind === 'select' && (
                                <>
                                    <LemonLabel>Options (one per line)</LemonLabel>
                                    <LemonTextArea
                                        value={(block.options ?? []).join('\n')}
                                        onChange={(text) => onBlock(block.id, { options: text.split('\n') })}
                                        aria-label="Dropdown options"
                                    />
                                </>
                            )}
                            {block.input_kind === 'slider' && (
                                <>
                                    <LemonLabel>Minimum</LemonLabel>
                                    <LemonInput
                                        type="number"
                                        value={block.min ?? 0}
                                        onChange={(min) => onBlock(block.id, { min: min ?? 0 })}
                                    />
                                    <LemonLabel>Maximum</LemonLabel>
                                    <LemonInput
                                        type="number"
                                        value={block.max ?? 100}
                                        onChange={(max) => onBlock(block.id, { max: max ?? 100 })}
                                    />
                                    <LemonLabel>Step</LemonLabel>
                                    <LemonInput
                                        type="number"
                                        value={block.step ?? 1}
                                        min={0.000001}
                                        onChange={(step) => onBlock(block.id, { step: step ?? 1 })}
                                    />
                                </>
                            )}
                            <p className="text-xs text-secondary">
                                Changing this input updates the notebook variable. Run the notebook to refresh dependent
                                results.
                            </p>
                        </>
                    )}
                </>
            )}
        </aside>
    )
}
