import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { AutoSizer } from 'lib/components/AutoSizer'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconArrowDown, IconArrowUp, IconTuning } from 'lib/lemon-ui/icons'

import { tracingConfigLogic } from '../../tracingConfigLogic'
import {
    addSpanColumn,
    availableBuiltInColumns,
    DEFAULT_SPAN_COLUMNS,
    moveSpanColumn,
    removeSpanColumn,
    SpanColumnConfig,
    spanColumnKey,
    spanColumnLabel,
} from './spanColumns'

function DraftColumnRow({
    column,
    isFirst,
    isLast,
    onMove,
    onRemove,
}: {
    column: SpanColumnConfig
    isFirst: boolean
    isLast: boolean
    onMove: (direction: 'up' | 'down') => void
    onRemove: () => void
}): JSX.Element {
    return (
        <div className="flex items-center gap-1 px-2 py-1 my-1 rounded bg-accent-highlight-secondary">
            <span className="truncate">{spanColumnLabel(column)}</span>
            {column.type === 'attribute' && <span className="text-xs text-muted">attribute</span>}
            <div className="flex-1" />
            <LemonButton
                size="small"
                tooltip="Move up"
                icon={<IconArrowUp />}
                disabledReason={isFirst ? 'Already the first column' : undefined}
                onClick={() => onMove('up')}
                data-attr="tracing-column-move-up"
            />
            <LemonButton
                size="small"
                tooltip="Move down"
                icon={<IconArrowDown />}
                disabledReason={isLast ? 'Already the last column' : undefined}
                onClick={() => onMove('down')}
                data-attr="tracing-column-move-down"
            />
            <LemonButton
                size="small"
                status="danger"
                tooltip="Remove"
                icon={<IconX />}
                onClick={onRemove}
                data-attr="tracing-column-remove"
            />
        </div>
    )
}

export function SpanColumnConfigurator(): JSX.Element {
    const { spanColumns } = useValues(tracingConfigLogic)
    const { setSpanColumns } = useActions(tracingConfigLogic)

    const [isOpen, setIsOpen] = useState(false)
    const [draft, setDraft] = useState<SpanColumnConfig[]>(spanColumns)

    const open = (): void => {
        setDraft(spanColumns)
        setIsOpen(true)
    }

    const save = (): void => {
        setSpanColumns(draft)
        setIsOpen(false)
    }

    const builtInOptions = useMemo(
        () => availableBuiltInColumns(draft).map((type) => ({ value: type, label: spanColumnLabel({ type }) })),
        [draft]
    )

    return (
        <>
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconTuning />}
                onClick={open}
                data-attr="tracing-table-column-selector"
            >
                Configure columns
            </LemonButton>
            <LemonModal
                isOpen={isOpen}
                title="Configure columns"
                onClose={() => setIsOpen(false)}
                footer={
                    <>
                        <div className="flex-1">
                            <LemonButton type="secondary" onClick={() => setDraft(DEFAULT_SPAN_COLUMNS)}>
                                Reset to defaults
                            </LemonButton>
                        </div>
                        <LemonButton type="secondary" onClick={() => setIsOpen(false)}>
                            Close
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={save}
                            disabledReason={draft.length === 0 ? 'Add at least one column' : undefined}
                            data-attr="tracing-column-apply"
                        >
                            Save
                        </LemonButton>
                    </>
                }
                className="w-full max-w-248"
            >
                <div className="flex flex-col gap-4">
                    <div className="w-full">
                        <h4 className="secondary uppercase text-secondary">Visible columns ({draft.length})</h4>
                        {draft.length === 0 ? (
                            <p className="text-muted">
                                No columns left. Add one below, or reset to the default columns.
                            </p>
                        ) : (
                            draft.map((column, index) => (
                                <DraftColumnRow
                                    key={spanColumnKey(column)}
                                    column={column}
                                    isFirst={index === 0}
                                    isLast={index === draft.length - 1}
                                    onMove={(direction) =>
                                        setDraft(moveSpanColumn(draft, spanColumnKey(column), direction))
                                    }
                                    onRemove={() => setDraft(removeSpanColumn(draft, spanColumnKey(column)))}
                                />
                            ))
                        )}
                    </div>
                    <div className="w-full">
                        <h4 className="secondary uppercase text-secondary">Add a built-in column</h4>
                        <LemonSelect
                            size="small"
                            placeholder="Pick a column"
                            disabledReason={
                                builtInOptions.length === 0 ? 'Every built-in column is already shown' : undefined
                            }
                            options={builtInOptions}
                            value={null}
                            onChange={(type) => type && setDraft(addSpanColumn(draft, { type }))}
                            data-attr="tracing-add-built-in-column"
                        />
                    </div>
                    <div className="w-full">
                        <h4 className="secondary uppercase text-secondary">Add an attribute column</h4>
                        <div className="h-[min(360px,50vh)]">
                            <AutoSizer
                                renderProp={({ height, width }) =>
                                    height && width ? (
                                        <TaxonomicFilter
                                            height={height}
                                            width={width}
                                            taxonomicGroupTypes={[
                                                TaxonomicFilterGroupType.SpanAttributes,
                                                TaxonomicFilterGroupType.SpanResourceAttributes,
                                            ]}
                                            value={undefined}
                                            onChange={(_group, value) => {
                                                // TaxonomicFilterValue admits null, which would persist a column keyed on "null".
                                                if (typeof value === 'string' && value) {
                                                    setDraft(
                                                        addSpanColumn(draft, {
                                                            type: 'attribute',
                                                            attributeKey: value,
                                                        })
                                                    )
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
