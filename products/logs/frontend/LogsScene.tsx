import { LemonButton, LemonCheckbox, LemonSegmentedButton, LemonTable, LemonTag, LemonTagType } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Sparkline } from 'lib/components/Sparkline'
import { TZLabel } from 'lib/components/TZLabel'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import { useEffect } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { LogMessage } from '~/queries/schema/schema-general'

import { DateRangeFilter } from './filters/DateRangeFilter'
import { SearchTermFilter } from './filters/SearchTermFilter'
import { SeverityLevelsFilter } from './filters/SeverityLevelsFilter'
import { logsLogic } from './logsLogic'

export const scene: SceneExport = {
    component: LogsScene,
}

export function LogsScene(): JSX.Element {
    const { wrapBody, logs, sparkline, logsLoading, hasRunQuery } = useValues(logsLogic)

    const labels: string[] = []
    const counts: number[] = []
    sparkline.forEach(([label, count]) => {
        labels.push(label)
        counts.push(count)
    })

    return (
        <div className="flex flex-col gap-y-2 h-screen">
            <Filters />
            {hasRunQuery ? (
                <>
                    {sparkline.length > 0 && <Sparkline labels={labels} data={counts} className="w-full" />}
                    <DisplayOptions />
                    <div className="flex-1">
                        <LemonTable
                            hideScrollbar
                            dataSource={logs}
                            loading={logsLoading}
                            size="small"
                            // disableTableWhileLoading={true}
                            columns={[
                                {
                                    title: 'Timestamp',
                                    key: 'timestamp',
                                    dataIndex: 'timestamp',
                                    width: 0,
                                    render: (timestamp) => <TZLabel time={timestamp as string} />,
                                },
                                {
                                    title: 'Level',
                                    key: 'severity_text',
                                    dataIndex: 'severity_text',
                                    width: 0,
                                    render: (_, record) => <LogTag level={record.severity_text} />,
                                },
                                {
                                    title: 'Message',
                                    key: 'body',
                                    dataIndex: 'body',
                                    render: (body) => (
                                        <div className={cn(wrapBody ? '' : 'whitespace-nowrap')}>{body}</div>
                                    ),
                                },
                            ]}
                            expandable={{
                                noIndent: true,
                                expandedRowRender: (log) => <ExpandedLog log={log} />,
                            }}
                        />
                    </div>
                </>
            ) : (
                <div>Run your query to start seeing logs</div>
            )}
        </div>
    )
}

const ExpandedLog = ({ log }: { log: LogMessage }): JSX.Element => {
    const attributes = JSON.parse(log.attributes)
    const rows = Object.entries(attributes).map(([key, value]) => ({ key, value }))

    return (
        <LemonTable
            embedded
            showHeader={false}
            columns={[
                {
                    title: 'Key',
                    key: 'key',
                    dataIndex: 'key',
                    width: 0,
                },
                {
                    title: 'Value',
                    key: 'value',
                    dataIndex: 'value',
                },
            ]}
            dataSource={rows}
        />
    )
}

const LogTag = ({ level }: { level: LogMessage['severity_text'] }): JSX.Element => {
    const type = (
        {
            debug: 'completion',
            info: 'caution',
            warn: 'warning',
            error: 'danger',
        } as Record<LogMessage['severity_text'], LemonTagType>
    )[level]

    return <LemonTag type={type}>{level}</LemonTag>
}

const Filters = (): JSX.Element => {
    const { hasRunQuery, logsLoading } = useValues(logsLogic)
    const { runQuery } = useActions(logsLogic)

    return (
        <div className="flex flex-col gap-y-1.5">
            <div className="flex justify-between gap-y-2">
                <div className="flex gap-x-1">
                    {/* <AttributesFilter /> */}
                    <SeverityLevelsFilter />
                </div>
                <div className="flex gap-x-1">
                    <DateRangeFilter />
                    <LemonButton
                        size="small"
                        icon={hasRunQuery ? <IconRefresh /> : <IconRefresh />}
                        type="secondary"
                        onClick={runQuery}
                        loading={logsLoading}
                    >
                        {hasRunQuery ? 'Refresh' : 'Run'}
                    </LemonButton>
                </div>
            </div>
            <SearchTermFilter />
        </div>
    )
}

const DisplayOptions = (): JSX.Element => {
    const { orderBy, wrapBody } = useValues(logsLogic)
    const { setOrderBy, setWrapBody } = useActions(logsLogic)

    return (
        <div className="flex gap-x-2">
            <LemonSegmentedButton
                value={orderBy}
                onChange={setOrderBy}
                options={[
                    {
                        value: 'earliest',
                        label: 'Earliest',
                    },
                    {
                        value: 'latest',
                        label: 'Latest',
                    },
                ]}
                size="small"
            />
            <LemonCheckbox checked={wrapBody} bordered onChange={setWrapBody} label="Wrap message" size="small" />
        </div>
    )
}
