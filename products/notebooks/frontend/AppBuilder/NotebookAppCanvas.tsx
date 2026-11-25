import { CSSProperties, useMemo } from 'react'

import { IconChevronDown, IconCopy, IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import type { NotebookBlockNode } from 'lib/components/MarkdownNotebook/types'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { cn } from 'lib/utils/css-classes'
import type { NotebookStaleReason } from 'scenes/notebooks/Notebook/notebookNodeStalenessLogic'
import type { NotebookVariable, NotebookVariableValue } from 'scenes/notebooks/Notebook/notebookVariables'

import type { NotebookAppLayoutApi } from '../generated/api.schemas'
import { NotebookAppBlock } from './NotebookAppBlock'

export function NotebookAppCanvas({
    layout,
    activeTab,
    cells,
    staleNodeIds,
    variables,
    editing,
    selectedId,
    canInteract,
    onSelect,
    onMove,
    onMoveBy,
    onDuplicate,
    onRemove,
    onSource,
    onInput,
    onCellOutput,
    renderOutput,
}: {
    layout: NotebookAppLayoutApi
    activeTab: string
    cells: NotebookBlockNode[]
    staleNodeIds: Record<string, NotebookStaleReason>
    variables: NotebookVariable[]
    editing: boolean
    selectedId: string | null
    canInteract: boolean
    onSelect?: (id: string) => void
    onMove?: (id: string, beforeId: string) => void
    onMoveBy?: (id: string, direction: number) => void
    onDuplicate?: (id: string) => void
    onRemove?: (id: string) => void
    onSource?: (id: string) => void
    onInput: (name: string, value: NotebookVariableValue) => void
    onCellOutput?: (nodeId: string, markdown: string) => void
    renderOutput?: (cell: NotebookBlockNode) => JSX.Element | undefined
}): JSX.Element {
    const cellsById = useMemo(() => {
        const index = new Map<string, NotebookBlockNode>()
        for (const cell of cells) {
            if (!index.has(cell.id)) {
                index.set(cell.id, cell)
            }
        }
        return index
    }, [cells])
    const blocks = layout.blocks.filter((block) => block.tab_id === activeTab)
    return (
        <div className="NotebookAppBuilder__grid" data-attr="notebook-app-canvas">
            {blocks.map((block, index) => (
                <div
                    key={block.id}
                    className="NotebookAppBuilder__slot"
                    style={{ '--app-block-width': block.width ?? 12 } as CSSProperties}
                    onDragOver={editing ? (event) => event.preventDefault() : undefined}
                    onDrop={
                        editing
                            ? (event) => {
                                  event.preventDefault()
                                  onMove?.(event.dataTransfer.getData('application/x-notebook-app-block'), block.id)
                              }
                            : undefined
                    }
                >
                    <LemonCard
                        hoverEffect={false}
                        className={cn('h-full min-w-0 p-4', editing && selectedId === block.id && 'border-accent')}
                    >
                        {editing && (
                            <div className="flex items-center justify-between gap-2 mb-3 border-b pb-2">
                                <LemonButton
                                    size="xsmall"
                                    type={selectedId === block.id ? 'secondary' : 'tertiary'}
                                    icon={<IconPencil />}
                                    onClick={() => onSelect?.(block.id)}
                                    data-attr="notebook-app-edit-component"
                                >
                                    {block.kind === 'cell'
                                        ? 'Notebook cell'
                                        : block.kind === 'input'
                                          ? 'Input'
                                          : block.kind === 'divider'
                                            ? 'Divider'
                                            : 'Text'}
                                </LemonButton>
                                <div className="flex items-center gap-1">
                                    <button
                                        type="button"
                                        draggable
                                        aria-label="Drag component"
                                        title="Drag to reorder"
                                        className="cursor-grab px-2 text-secondary"
                                        onDragStart={(event) =>
                                            event.dataTransfer.setData('application/x-notebook-app-block', block.id)
                                        }
                                    >
                                        ⠿
                                    </button>
                                    <LemonMenu
                                        items={[
                                            {
                                                label: 'Move up',
                                                icon: <IconChevronDown className="rotate-180" />,
                                                disabledReason: index === 0 ? 'Already first' : undefined,
                                                onClick: () => onMoveBy?.(block.id, -1),
                                            },
                                            {
                                                label: 'Move down',
                                                icon: <IconChevronDown />,
                                                disabledReason:
                                                    index === blocks.length - 1 ? 'Already last' : undefined,
                                                onClick: () => onMoveBy?.(block.id, 1),
                                            },
                                            {
                                                label: 'Duplicate',
                                                icon: <IconCopy />,
                                                onClick: () => onDuplicate?.(block.id),
                                            },
                                            ...(block.kind === 'cell'
                                                ? [
                                                      {
                                                          label: 'Open source cell',
                                                          onClick: () => onSource?.(block.node_id || ''),
                                                      },
                                                  ]
                                                : []),
                                            {
                                                label: 'Remove from app',
                                                icon: <IconTrash />,
                                                status: 'danger',
                                                onClick: () => onRemove?.(block.id),
                                            },
                                        ]}
                                    >
                                        <LemonButton size="xsmall" aria-label="Component actions">
                                            •••
                                        </LemonButton>
                                    </LemonMenu>
                                </div>
                            </div>
                        )}
                        <NotebookAppBlock
                            block={block}
                            cell={cellsById.get(block.node_id ?? '')}
                            stale={!!staleNodeIds[block.node_id || '']}
                            onSource={!editing ? onSource : undefined}
                            variables={variables}
                            canInteract={canInteract}
                            onInput={onInput}
                            onCellOutput={onCellOutput}
                            renderOutput={renderOutput}
                        />
                    </LemonCard>
                </div>
            ))}
            {!blocks.length && (
                <div className="col-span-12 border border-dashed rounded p-8 text-center text-secondary">
                    <h3>{editing ? 'Build your app' : 'No components on this tab'}</h3>
                    <p>
                        {editing
                            ? 'Add notebook cells, text, and inputs from the component panel.'
                            : 'Choose another tab or ask an editor to add components.'}
                    </p>
                </div>
            )}
        </div>
    )
}
