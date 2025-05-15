import { LemonTable, LemonTag, LemonTagType } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Sparkline } from 'lib/components/Sparkline'
import { cn } from 'lib/utils/css-classes'
import { SceneExport } from 'scenes/sceneTypes'

import { DEFAULT_LOGS, logsLogic } from './logsLogic'
import { LogMessage } from './types'

export const scene: SceneExport = {
    component: LogsScene,
}

export function LogsScene(): JSX.Element {
    // TODO: figure out why this breaks frontend rendering
    const { wrapBody } = useValues(logsLogic)
    // const wrapBody = true

    const logs = DEFAULT_LOGS

    return (
        <div className="flex flex-col gap-y-2 h-screen">
            <Sparkline labels={['bucket 1']} data={[1]} className="w-full" />
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
