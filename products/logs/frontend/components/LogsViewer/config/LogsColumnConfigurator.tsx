import { DndContext, DragEndEvent } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'

import { IconPencil, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, Tooltip } from '@posthog/lemon-ui'

import { AutoSizer } from 'lib/components/AutoSizer'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroup, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconTuning, SortableDragIcon } from 'lib/lemon-ui/icons'

import { NodeKind } from '~/queries/schema/schema-general'

import { logsViewerLogic } from '../logsViewerLogic'
import { DEFAULT_LOGS_COLUMNS, LogsColumnConfig, columnLabel } from './columns'
import { logsColumnConfiguratorLogic } from './logsColumnConfiguratorLogic'

// The Logs taxonomic group's fixed keys, mapped onto built-in column types.
const LOGS_KEY_TO_COLUMN_TYPE: Record<string, LogsColumnConfig['type']> = {
    message: 'message',
    severity_level: 'level',
    trace_id: 'trace_id',
    span_id: 'span_id',
}

// Maps the attribute groups onto the custom-column shorthand prefix.
const TAXONOMIC_GROUP_TO_PREFIX: Partial<Record<TaxonomicFilterGroupType, string>> = {
    [TaxonomicFilterGroupType.LogAttributes]: 'attributes',
    [TaxonomicFilterGroupType.LogResourceAttributes]: 'resource_attributes',
}

function taxonomicSelectionToColumn(group: TaxonomicFilterGroup, value: string): Omit<LogsColumnConfig, 'id'> | null {
    if (group.type === TaxonomicFilterGroupType.Logs) {
        const type = LOGS_KEY_TO_COLUMN_TYPE[value]
        return type ? { type } : null
    }
    if (group.type === TaxonomicFilterGroupType.HogQLExpression) {
        return { type: 'custom', expression: value }
    }
    const prefix = TAXONOMIC_GROUP_TO_PREFIX[group.type]
    return prefix ? { type: 'custom', name: value, expression: `${prefix}.${value}` } : null
}

function SelectedColumnRow({ column }: { column: LogsColumnConfig }): JSX.Element {
    const { id } = useValues(logsViewerLogic)
    const { editingColumnId } = useValues(logsColumnConfiguratorLogic({ id }))
    const { updateDraftColumn, removeDraftColumn, setEditingColumnId } = useActions(logsColumnConfiguratorLogic({ id }))
    const { setNodeRef, attributes, transform, transition, listeners } = useSortable({ id: column.id })

    const isEditing = editingColumnId === column.id

    return (
        <div ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition }} {...attributes}>
            <div className="flex items-center justify-start px-2 py-1 my-1 rounded bg-accent-highlight-secondary">
                <span {...listeners} className="pr-2 text-secondary cursor-move">
                    <SortableDragIcon />
                </span>
                <span className="truncate">{columnLabel(column)}</span>
                {column.type === 'custom' && column.name && column.expression && column.expression !== column.name && (
                    <span className="ml-2 text-xs text-muted font-mono truncate">{column.expression}</span>
                )}
                <div className="flex-1" />
                {column.type === 'custom' && (
                    <Tooltip title="Edit">
                        <LemonButton size="small" onClick={() => setEditingColumnId(isEditing ? null : column.id)}>
                            <IconPencil data-attr="logs-column-edit-icon" />
                        </LemonButton>
                    </Tooltip>
                )}
                <Tooltip title="Remove">
                    <LemonButton size="small" status="danger" onClick={() => removeDraftColumn(column.id)}>
                        <IconX data-attr="logs-column-remove-icon" />
                    </LemonButton>
                </Tooltip>
            </div>
            {isEditing && (
                <div className="flex items-center gap-2 pl-8 pb-2">
                    <LemonInput
                        size="small"
                        placeholder="Name (optional)"
                        value={column.name ?? ''}
                        onChange={(name) => updateDraftColumn(column.id, { name: name || undefined })}
                        data-attr="logs-column-name-input"
                    />
                    <LemonInput
                        size="small"
                        className="flex-1 font-mono"
                        placeholder="attributes.http.url or upper(level)"
                        value={column.expression ?? ''}
                        onChange={(expression) => updateDraftColumn(column.id, { expression })}
                        data-attr="logs-column-expression-input"
                    />
                </div>
            )}
        </div>
    )
}

/**
 * "Configure columns" modal for the logs table, following the DataTable ColumnConfigurator
 * pattern: a drag-to-reorder visible-columns list plus an embedded TaxonomicFilter of
 * available columns. Edits accumulate in a draft and only commit (and re-run the query) on Save.
 */
export function LogsColumnConfigurator(): JSX.Element {
    const { id } = useValues(logsViewerLogic)
    const configuratorLogic = logsColumnConfiguratorLogic({ id })
    const { isOpen, draft, draftErrors } = useValues(configuratorLogic)
    const { openConfigurator, closeConfigurator, setDraft, addDraftColumn, moveDraftColumn, applyDraft } =
        useActions(configuratorLogic)

    const onDragEnd = ({ active, over }: DragEndEvent): void => {
        if (over && active.id !== over.id) {
            moveDraftColumn(
                draft.findIndex((column) => column.id === active.id),
                draft.findIndex((column) => column.id === over.id)
            )
        }
    }

    return (
        <>
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconTuning />}
                onClick={openConfigurator}
                data-attr="logs-table-column-selector"
            >
                Configure columns
            </LemonButton>
            <LemonModal
                isOpen={isOpen}
                title="Configure columns"
                onClose={closeConfigurator}
                footer={
                    <>
                        <div className="flex-1">
                            <LemonButton type="secondary" onClick={() => setDraft(DEFAULT_LOGS_COLUMNS)}>
                                Reset to defaults
                            </LemonButton>
                        </div>
                        <LemonButton type="secondary" onClick={closeConfigurator}>
                            Close
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={applyDraft}
                            disabledReason={draftErrors ?? undefined}
                            data-attr="logs-column-apply"
                        >
                            Save
                        </LemonButton>
                    </>
                }
                className="w-full max-w-248"
            >
                <div className="flex flex-col gap-4">
                    <div className="w-full">
                        <h4 className="secondary uppercase text-secondary">
                            Visible columns ({draft.length}) - Drag to reorder
                        </h4>
                        <DndContext onDragEnd={onDragEnd} modifiers={[restrictToVerticalAxis, restrictToParentElement]}>
                            <SortableContext
                                items={draft.map((column) => column.id)}
                                strategy={verticalListSortingStrategy}
                            >
                                {draft.map((column) => (
                                    <SelectedColumnRow key={column.id} column={column} />
                                ))}
                            </SortableContext>
                        </DndContext>
                    </div>
                    <div className="w-full">
                        <h4 className="secondary uppercase text-secondary">Available columns</h4>
                        <div className="h-[min(480px,60vh)]">
                            <AutoSizer
                                renderProp={({ height, width }) =>
                                    height && width ? (
                                        <TaxonomicFilter
                                            height={height}
                                            width={width}
                                            taxonomicGroupTypes={[
                                                TaxonomicFilterGroupType.Logs,
                                                TaxonomicFilterGroupType.LogAttributes,
                                                TaxonomicFilterGroupType.LogResourceAttributes,
                                                TaxonomicFilterGroupType.HogQLExpression,
                                            ]}
                                            value={undefined}
                                            metadataSource={{
                                                kind: NodeKind.HogQLQuery,
                                                query: 'select * from logs',
                                            }}
                                            onChange={(group, value) => {
                                                const column = taxonomicSelectionToColumn(group, String(value))
                                                if (column) {
                                                    addDraftColumn(column)
                                                }
                                            }}
                                            popoverEnabled={false}
                                            selectFirstItem={false}
                                            selectingKeyOnly
                                        />
                                    ) : null
                                }
                            />
                        </div>
                    </div>
                </div>
            </LemonModal>
        </>
    )
}
