import { useActions } from 'kea'

import { IconMinusSquare, IconPlusSquare } from '@posthog/icons'
import { LemonButton, LemonTable } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { PropertyFilterType, PropertyOperator } from '~/types'

import { tracingFiltersLogic } from 'products/tracing/frontend/tracingFiltersLogic'

interface AttributeRow {
    key: string
    value: string
}

export interface SpanAttributesProps {
    attributes: Record<string, string>
    title: string
    emptyLabel?: string
    /** @default true */
    showFilterActions?: boolean
    /** Required when `showFilterActions` is true. */
    propertyType?: PropertyFilterType.SpanAttribute | PropertyFilterType.SpanResourceAttribute
}

export function SpanAttributes({
    attributes,
    title,
    emptyLabel = 'No attributes',
    showFilterActions = true,
    propertyType,
}: SpanAttributesProps): JSX.Element {
    const { addFilter } = useActions(tracingFiltersLogic)

    const rows: AttributeRow[] = Object.entries(attributes).map(([key, value]) => ({ key, value }))

    const columns: LemonTableColumns<AttributeRow> = [
        ...(showFilterActions
            ? [
                  {
                      key: 'actions',
                      width: 0,
                      render: (_: unknown, record: AttributeRow) => (
                          <div className="flex gap-x-0">
                              <LemonButton
                                  tooltip="Add as filter"
                                  size="xsmall"
                                  onClick={(e) => {
                                      e.stopPropagation()
                                      addFilter(record.key, record.value, PropertyOperator.Exact, propertyType)
                                  }}
                              >
                                  <IconPlusSquare />
                              </LemonButton>
                              <LemonButton
                                  tooltip="Exclude as filter"
                                  size="xsmall"
                                  onClick={(e) => {
                                      e.stopPropagation()
                                      addFilter(record.key, record.value, PropertyOperator.IsNot, propertyType)
                                  }}
                              >
                                  <IconMinusSquare />
                              </LemonButton>
                          </div>
                      ),
                  },
              ]
            : []),
        {
            title: 'Key',
            key: 'key',
            dataIndex: 'key',
            width: 0,
            render: (_, record): JSX.Element => (
                <span className="font-mono text-xs text-muted whitespace-nowrap">{record.key}</span>
            ),
        },
        {
            title: 'Value',
            key: 'value',
            dataIndex: 'value',
            render: (_, record): JSX.Element => {
                if (record.value === '') {
                    return <span className="font-mono text-xs text-muted italic">(empty)</span>
                }
                return (
                    <CopyToClipboardInline
                        explicitValue={record.value}
                        description="attribute value"
                        iconSize="xsmall"
                        iconPosition="start"
                        selectable
                        className="gap-1 font-mono text-xs"
                    >
                        {record.value}
                    </CopyToClipboardInline>
                )
            },
        },
    ]

    return (
        <div className="bg-primary overflow-hidden rounded border border-border">
            <div className="px-3 py-2 bg-bg-light border-b border-border">
                <span className="text-xs font-semibold text-muted uppercase">{title}</span>
            </div>
            {rows.length === 0 ? (
                <div className="px-3 py-2 text-xs text-muted italic">{emptyLabel}</div>
            ) : (
                <LemonTable embedded showHeader={false} size="small" rowKey="key" columns={columns} dataSource={rows} />
            )}
        </div>
    )
}
