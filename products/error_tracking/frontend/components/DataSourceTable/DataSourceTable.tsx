import { BuiltLogic, useActions, useValues } from 'kea'
import { Children, MouseEvent, ReactElement, isValidElement, useCallback } from 'react'
import { P, match } from 'ts-pattern'

import { LemonButton, LemonTable, LemonTableColumn, LemonTableProps } from '@posthog/lemon-ui'

import type { DataSourceLogic } from './types'

export interface DataSourceTableProps<T extends Record<string, any>> {
    dataSource: BuiltLogic<DataSourceLogic<T>>
    className?: string
    children?: React.ReactNode
    embedded?: boolean
    expandable?: LemonTableProps<T>['expandable']
    onRowClick?: (item: T, evt: MouseEvent) => void
    rowRibbonColor?: LemonTableProps<T>['rowRibbonColor']
}

export function DataSourceTable<T extends Record<string, any>>({
    dataSource,
    className,
    embedded = false,
    onRowClick,
    rowRibbonColor,
    expandable,
    children,
}: DataSourceTableProps<T>): JSX.Element {
    const { items, itemsLoading } = useValues(dataSource)

    const columns = Children.toArray(children)
        .filter((child) => isValidElement(child))
        .map((child) => {
            const props = (child as ReactElement).props as DataSourceTableColumnProps<T>
            return {
                title: props.title,
                align: props.align,
                width: props.width,
                render: (_, record: T, recordIndex: number, rowCount: number) =>
                    props.cellRenderer(record, recordIndex, rowCount),
            } as LemonTableColumn<T, keyof T | undefined>
        })

    const onRow = useCallback(
        (record: T) => {
            if (!onRowClick) {
                return {}
            }
            return {
                // onClick handler adds style to row we don't want
                onClick: (event: MouseEvent) => {
                    onRowClick(record, event)
                },
                className: 'hover:bg-fill-highlight-50',
            }
        },
        [onRowClick]
    )

    return (
        <LemonTable
            dataSource={items}
            columns={columns}
            loading={itemsLoading}
            embedded={embedded}
            onRow={onRow}
            className={className}
            footer={<DataSourceTableFooter dataSource={dataSource} />}
            rowRibbonColor={rowRibbonColor}
            expandable={expandable}
        />
    )
}

export function DataSourceTableFooter<T extends Record<string, any>>({
    dataSource,
}: Pick<DataSourceTableProps<T>, 'dataSource'>): JSX.Element {
    const { itemsLoading, canLoadNextData } = useValues(dataSource)
    const { loadNextData } = useActions(dataSource)

    return (
        <div className="p-1">
            <LemonButton
                className="rounded-tl-none rounded-tr-none"
                loading={itemsLoading}
                center
                fullWidth
                disabledReason={match([itemsLoading, canLoadNextData])
                    .with([true, P.any], () => 'Loading...')
                    .with([P.any, false], () => 'Increase date range or change filters')
                    .otherwise(() => undefined)}
                onClick={() => loadNextData()}
            >
                {itemsLoading && <span>Loading...</span>}
                {!itemsLoading && !canLoadNextData && <span>No more entries</span>}
                {!itemsLoading && canLoadNextData && <span>Load More</span>}
            </LemonButton>
        </div>
    )
}

export interface DataSourceTableColumnProps<T> {
    title?: string
    align?: 'left' | 'right' | 'center'
    width?: string
    cellRenderer: (item: T, itemIdx: number, rowCount: number) => React.ReactNode
}

/* eslint-disable @typescript-eslint/no-unused-vars */
export function DataSourceTableColumn<T>(_: DataSourceTableColumnProps<T>): JSX.Element {
    /* eslint-enable @typescript-eslint/no-unused-vars */
    return <></>
}
