import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonTable, Spinner } from '@posthog/lemon-ui'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { PropsWithChildren } from 'react'
import { match } from 'ts-pattern'
import { exceptionCardLogic } from './ExceptionCard/exceptionCardLogic'
import { useValues } from 'kea'

export function ContextLoader({ children }: PropsWithChildren<{}>): JSX.Element {
    const { loading } = useValues(exceptionCardLogic)

    return (
        <>
            {match(loading)
                .with(true, () => (
                    <div className="flex justify-center w-full h-32 items-center">
                        <Spinner />
                    </div>
                ))
                .with(false, () => children)
                .exhaustive()}
        </>
    )
}

export function ContextTable({ entries }: { entries: [string, unknown][] }): JSX.Element {
    return (
        <LemonTable
            embedded
            size="small"
            dataSource={entries
                .filter(([, value]) => value !== undefined)
                .map(([key, value]) => ({
                    key,
                    value: String(value),
                }))}
            showHeader={false}
            columns={[
                {
                    title: 'Key',
                    key: 'key',
                    dataIndex: 'key',
                    width: 0,
                    className: 'font-medium bg-inherit',
                    render: (dataValue, record) => (
                        <div className="flex gap-x-2 justify-between items-center">
                            <div>{dataValue}</div>
                            <LemonButton
                                size="xsmall"
                                tooltip="Copy value"
                                className="invisible group-hover:visible"
                                onClick={() =>
                                    copyToClipboard(record.value).catch((error) => {
                                        console.error('Failed to copy to clipboard:', error)
                                    })
                                }
                            >
                                <IconCopy />
                            </LemonButton>
                        </div>
                    ),
                },
                {
                    title: 'Value',
                    key: 'value',
                    dataIndex: 'value',
                    className: 'whitespace-nowrap',
                },
            ]}
            rowClassName="even:bg-fill-tertiary odd:bg-surface-primary group"
            firstColumnSticky
        />
    )
}
