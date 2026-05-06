import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconArrowDown, IconArrowUp, IconTableChart, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSegmentedButton, Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { logsColumnsModalLogic } from 'products/logs/frontend/components/LogsViewer/LogsColumnsModal/logsColumnsModalLogic'
import { logsViewerLogic } from 'products/logs/frontend/components/LogsViewer/logsViewerLogic'

export interface LogsColumnsModalProps {
    viewerId: string
}

export function LogsColumnsModal({ viewerId }: LogsColumnsModalProps): JSX.Element {
    const { modalVisible, searchQuery, attributeTypeTab, attributeKeySuggestions, attributeKeySuggestionsLoading } =
        useValues(logsColumnsModalLogic({ viewerId }))
    const { closeModal, setSearchQuery, setAttributeTypeTab, openModal } = useActions(
        logsColumnsModalLogic({ viewerId })
    )
    const { attributeColumns } = useValues(logsViewerLogic({ id: viewerId }))
    const { toggleAttributeColumn, removeAttributeColumn, setAttributeColumnsFromOrderedKeys } = useActions(
        logsViewerLogic({ id: viewerId })
    )
    const [customKey, setCustomKey] = useState('')

    const moveColumn = (index: number, direction: 'up' | 'down'): void => {
        const keys = [...attributeColumns]
        const target = direction === 'up' ? index - 1 : index + 1
        if (target < 0 || target >= keys.length) {
            return
        }
        const next = [...keys]
        const tmp = next[index]
        next[index] = next[target]!
        next[target] = tmp!
        setAttributeColumnsFromOrderedKeys(next)
    }

    const addCustomKey = (): void => {
        const key = customKey.trim()
        if (!key) {
            return
        }
        if (!attributeColumns.includes(key)) {
            setAttributeColumnsFromOrderedKeys([...attributeColumns, key])
        }
        setCustomKey('')
    }

    return (
        <>
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconTableChart />}
                onClick={() => openModal()}
                data-attr="logs-columns-button"
            >
                Columns
            </LemonButton>
            <LemonModal
                isOpen={modalVisible}
                onClose={closeModal}
                title="Log table columns"
                width={640}
                footer={
                    <div className="flex justify-end">
                        <LemonButton type="primary" onClick={closeModal}>
                            Done
                        </LemonButton>
                    </div>
                }
            >
                <div className="flex flex-col gap-4">
                    <p className="text-muted text-sm m-0">
                        Add log or resource attributes as columns between timestamp and message. Width and order can
                        still be adjusted from the table header.
                    </p>

                    <div>
                        <div className="text-xs font-semibold text-muted uppercase mb-2">Current columns</div>
                        {attributeColumns.length === 0 ? (
                            <div className="text-muted text-sm border border-dashed border-border rounded p-3">
                                No attribute columns yet. Add keys below or open a log and use &quot;Add as column&quot;
                                on any attribute.
                            </div>
                        ) : (
                            <ul className="flex flex-col gap-1 list-none m-0 p-0 max-h-48 overflow-y-auto">
                                {attributeColumns.map((key, index) => (
                                    <li
                                        key={key}
                                        className={cn(
                                            'flex items-center justify-between gap-2 rounded border border-border px-2 py-1.5 bg-bg-light'
                                        )}
                                    >
                                        <span className="font-mono text-xs truncate" title={key}>
                                            {key}
                                        </span>
                                        <div className="flex items-center gap-0 shrink-0">
                                            <LemonButton
                                                icon={<IconArrowUp />}
                                                size="xsmall"
                                                disabled={index === 0}
                                                onClick={() => moveColumn(index, 'up')}
                                                tooltip="Move up"
                                            />
                                            <LemonButton
                                                icon={<IconArrowDown />}
                                                size="xsmall"
                                                disabled={index === attributeColumns.length - 1}
                                                onClick={() => moveColumn(index, 'down')}
                                                tooltip="Move down"
                                            />
                                            <LemonButton
                                                icon={<IconTrash />}
                                                size="xsmall"
                                                status="danger"
                                                onClick={() => removeAttributeColumn(key)}
                                                tooltip="Remove column"
                                            />
                                        </div>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>

                    <div>
                        <div className="text-xs font-semibold text-muted uppercase mb-2">Add from telemetry keys</div>
                        <LemonSegmentedButton
                            size="small"
                            value={attributeTypeTab}
                            onChange={(value) => setAttributeTypeTab(value as 'log' | 'resource')}
                            options={[
                                { value: 'log' as const, label: 'Log attributes' },
                                { value: 'resource' as const, label: 'Resource attributes' },
                            ]}
                        />
                        <LemonInput
                            className="mt-2"
                            placeholder="Search keys (e.g. trace, service, http…)"
                            value={searchQuery}
                            onChange={setSearchQuery}
                            autoFocus
                        />
                        <div className="mt-2 min-h-32 max-h-48 overflow-y-auto border border-border rounded">
                            {attributeKeySuggestionsLoading ? (
                                <div className="flex justify-center p-4">
                                    <Spinner />
                                </div>
                            ) : attributeKeySuggestions.length === 0 ? (
                                <div className="text-muted text-sm p-3 m-0">
                                    No keys returned for this tab, time range, and filters. Try a shorter time range,
                                    narrow filters, or use a custom key below.
                                </div>
                            ) : (
                                <ul className="m-0 p-0 list-none">
                                    {attributeKeySuggestions.map((row) => {
                                        const active = attributeColumns.includes(row.name)
                                        return (
                                            <li
                                                key={`${row.name}-${row.propertyFilterType}`}
                                                className="flex items-center justify-between gap-2 px-2 py-1.5 border-b border-border last:border-b-0 hover:bg-bg-light"
                                            >
                                                <span className="font-mono text-xs truncate" title={row.name}>
                                                    {row.name}
                                                </span>
                                                <LemonButton
                                                    size="xsmall"
                                                    type={active ? 'primary' : 'secondary'}
                                                    onClick={() => toggleAttributeColumn(row.name)}
                                                >
                                                    {active ? 'Remove' : 'Add'}
                                                </LemonButton>
                                            </li>
                                        )
                                    })}
                                </ul>
                            )}
                        </div>
                    </div>

                    <div>
                        <div className="text-xs font-semibold text-muted uppercase mb-2">Add custom key</div>
                        <div className="flex gap-2">
                            <LemonInput
                                className="flex-1"
                                placeholder="e.g. trace_id or my.custom.attribute"
                                value={customKey}
                                onChange={setCustomKey}
                                onPressEnter={addCustomKey}
                            />
                            <LemonButton type="secondary" onClick={addCustomKey} disabled={!customKey.trim()}>
                                Add
                            </LemonButton>
                        </div>
                    </div>
                </div>
            </LemonModal>
        </>
    )
}
