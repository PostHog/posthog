import { useState } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonTable } from '@posthog/lemon-ui'

import { uuid } from 'lib/utils/dom'
import {
    MAX_NOTEBOOK_VARIABLE_LIST_ITEMS,
    MAX_NOTEBOOK_VARIABLE_VALUE_CHARS,
} from 'scenes/notebooks/Notebook/notebookVariables'

export function NotebookAppTableInput({
    title,
    columns,
    disabled,
    onApply,
}: {
    title: string
    columns: { name: string; values: string[] }[]
    disabled: boolean
    onApply: (changes: Record<string, string[]>) => void
}): JSX.Element {
    const [rows, setRows] = useState(() =>
        Array.from({ length: Math.max(0, ...columns.map((column) => column.values.length)) }, (_, row) => ({
            id: uuid(),
            cells: columns.map((column) => column.values[row] ?? ''),
        }))
    )
    const [dirty, setDirty] = useState(false)
    const largeColumn = columns.find(
        (_, index) =>
            rows.reduce((length, row) => length + Array.from(row.cells[index]).length, 0) >
            MAX_NOTEBOOK_VARIABLE_VALUE_CHARS
    )
    return (
        <section aria-label={title} className="flex flex-col gap-2">
            <h3 className="m-0">{title}</h3>
            <LemonTable
                size="small"
                dataSource={rows}
                rowKey="id"
                pagination={{ pageSize: 10, hideOnSinglePage: true }}
                emptyState="Add a row to enter values."
                columns={[
                    ...columns.map((column, index) => ({
                        title: column.name,
                        key: column.name,
                        render: (_: unknown, row: (typeof rows)[number]) => (
                            <LemonInput
                                aria-label={`${column.name}, row ${rows.indexOf(row) + 1}`}
                                value={row.cells[index]}
                                maxLength={MAX_NOTEBOOK_VARIABLE_VALUE_CHARS}
                                disabled={disabled}
                                onChange={(value) => {
                                    setDirty(true)
                                    setRows((current) =>
                                        current.map((r) =>
                                            r.id === row.id
                                                ? {
                                                      ...r,
                                                      cells: r.cells.map((cell, i) => (i === index ? value : cell)),
                                                  }
                                                : r
                                        )
                                    )
                                }}
                            />
                        ),
                    })),
                    {
                        title: '',
                        key: 'remove',
                        width: 0,
                        render: (_, row) => (
                            <LemonButton
                                icon={<IconTrash />}
                                size="small"
                                aria-label={`Remove row ${rows.indexOf(row) + 1}`}
                                disabledReason={disabled ? 'Open the app preview to edit rows' : undefined}
                                onClick={() => {
                                    setDirty(true)
                                    setRows((current) => current.filter((r) => r.id !== row.id))
                                }}
                            />
                        ),
                    },
                ]}
            />
            {largeColumn && (
                <LemonBanner type="warning">
                    Use at most {MAX_NOTEBOOK_VARIABLE_VALUE_CHARS} characters in {largeColumn.name}.
                </LemonBanner>
            )}
            <div className="flex items-center justify-between gap-2">
                <LemonButton
                    size="small"
                    icon={<IconPlus />}
                    type="secondary"
                    disabledReason={
                        disabled
                            ? 'Open the app preview to edit rows'
                            : rows.length >= MAX_NOTEBOOK_VARIABLE_LIST_ITEMS
                              ? `Use up to ${MAX_NOTEBOOK_VARIABLE_LIST_ITEMS} rows`
                              : undefined
                    }
                    onClick={() => {
                        setDirty(true)
                        setRows((current) => [...current, { id: uuid(), cells: columns.map(() => '') }])
                    }}
                >
                    Add row
                </LemonButton>
                <LemonButton
                    size="small"
                    type="primary"
                    data-attr="notebook-app-apply-table"
                    disabledReason={
                        disabled
                            ? 'Open the app preview to edit rows'
                            : largeColumn
                              ? 'Shorten the column values'
                              : !dirty
                                ? 'Edit the table first'
                                : undefined
                    }
                    onClick={() => {
                        onApply(
                            Object.fromEntries(
                                columns.map((column, i) => [column.name, rows.map((row) => row.cells[i])])
                            )
                        )
                        setDirty(false)
                    }}
                >
                    Apply changes
                </LemonButton>
            </div>
        </section>
    )
}
