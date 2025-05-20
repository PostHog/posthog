import { LemonButton, LemonCheckbox, LemonSegmentedButton, LemonTable, LemonTag, LemonTagType } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Sparkline } from 'lib/components/Sparkline'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import { useEffect } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { LogMessage } from '~/queries/schema/schema-general'

import { DateRangeFilter } from './filters/DateRangeFilter'
import { ResourceFilter } from './filters/ResourceFilter'
import { SearchTermFilter } from './filters/SearchTermFilter'
import { SeverityLevelsFilter } from './filters/SeverityLevelsFilter'
import { logsLogic } from './logsLogic'

export const scene: SceneExport = {
    component: LogsScene,
}

export function LogsScene(): JSX.Element {
    const { wrapBody, logs } = useValues(logsLogic)
    const { fetchLogs } = useActions(logsLogic)

    useEffect(() => {
        fetchLogs()
    }, [])

    return (
        <div className="flex flex-col gap-y-2 h-screen">
            <Filters />
            <Sparkline labels={['bucket 1']} data={[1]} className="w-full" />
            <DisplayOptions />
            <div className="flex-1">
                <LemonTable
                    hideScrollbar
                    dataSource={logs}
                    loading={false}
                    size="small"
                    columns={[
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
                            render: (body) => <div className={cn(wrapBody ? '' : 'whitespace-nowrap')}>{body}</div>,
                        },
                    ]}
                    expandable={{
                        noIndent: true,
                        expandedRowRender: (log) => <ExpandedLog log={log} />,
                    }}
                />
            </div>
        </div>
    )
}

const ExpandedLog = ({ log }: { log: LogMessage }): JSX.Element => {
    const rows = Object.entries(log.attributes).map(([key, value]) => ({ key, value }))

    return (
        <LemonTable
            embedded
            showHeader={false}
            columns={[
                {
                    title: 'Key',
                    key: 'key',
                    dataIndex: 'key',
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
    const { fetchLogs } = useActions(logsLogic)

    return (
        <div className="flex flex-col gap-y-1.5">
            <div className="flex justify-between gap-y-2">
                <div className="flex gap-x-1">
                    <ResourceFilter />
                    <SeverityLevelsFilter />
                </div>
                <div className="flex gap-x-1">
                    <DateRangeFilter />
                    <LemonButton size="small" icon={<IconRefresh />} type="secondary" onClick={fetchLogs}>
                        Refresh
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
