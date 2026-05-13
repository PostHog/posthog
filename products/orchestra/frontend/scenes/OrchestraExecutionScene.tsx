import { useValues } from 'kea'

import { LemonTable, LemonTableColumns, LemonTag } from '@posthog/lemon-ui'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { dayjs } from 'lib/dayjs'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import {
    orchestraExecutionLogic,
    OrchestraExecutionLogicProps,
    OrchestraEvent,
} from '../logics/orchestraExecutionLogic'

export const scene: SceneExport = {
    component: OrchestraExecutionScene,
    logic: orchestraExecutionLogic,
    paramsToProps: ({ params: { id } }): OrchestraExecutionLogicProps => ({
        executionId: id,
    }),
}

function OrchestraExecutionScene(): JSX.Element {
    const { execution, executionLoading } = useValues(orchestraExecutionLogic)

    if (executionLoading || !execution) {
        return (
            <>
                <SceneTitleSection title="Loading..." />
                <SceneContent>
                    <div>Loading execution details...</div>
                </SceneContent>
            </>
        )
    }

    const statusType =
        execution.status === 'COMPLETED' ? 'success' : execution.status === 'FAILED' ? 'danger' : 'default'

    const eventColumns: LemonTableColumns<OrchestraEvent> = [
        {
            title: 'Event ID',
            dataIndex: 'event_id',
            width: 80,
        },
        {
            title: 'Type',
            dataIndex: 'event_type',
            render: (_, record) => <LemonTag>{record.event_type}</LemonTag>,
        },
        {
            title: 'Time',
            dataIndex: 'timestamp',
            render: (_, record) => dayjs(record.timestamp).format('HH:mm:ss.SSS'),
        },
        {
            title: 'Attributes',
            dataIndex: 'attributes',
            render: (_, record) => (
                <CodeSnippet language={Language.JSON} wrap compact>
                    {JSON.stringify(record.attributes, null, 2)}
                </CodeSnippet>
            ),
        },
    ]

    return (
        <>
            <SceneTitleSection
                title={`Execution: ${execution.execution_id}`}
                description={execution.execution_type}
                buttons={<LemonTag type={statusType}>{execution.status}</LemonTag>}
            />
            <SceneContent>
                <div className="grid grid-cols-2 gap-4 mb-6">
                    <div>
                        <strong>Started:</strong> {dayjs(execution.started_at).format('YYYY-MM-DD HH:mm:ss')}
                    </div>
                    <div>
                        <strong>Finished:</strong>{' '}
                        {execution.finished_at
                            ? dayjs(execution.finished_at).format('YYYY-MM-DD HH:mm:ss')
                            : 'Running...'}
                    </div>
                    {execution.input != null && (
                        <div className="col-span-2">
                            <strong>Input:</strong>
                            <CodeSnippet language={Language.JSON} wrap compact>
                                {JSON.stringify(execution.input, null, 2)}
                            </CodeSnippet>
                        </div>
                    )}
                    {execution.result != null && (
                        <div className="col-span-2">
                            <strong>Result:</strong>
                            <CodeSnippet language={Language.JSON} wrap compact>
                                {JSON.stringify(execution.result, null, 2)}
                            </CodeSnippet>
                        </div>
                    )}
                    {execution.error != null && (
                        <div className="col-span-2">
                            <strong>Error:</strong>
                            <CodeSnippet language={Language.JSON} wrap compact>
                                {JSON.stringify(execution.error, null, 2)}
                            </CodeSnippet>
                        </div>
                    )}
                </div>

                <h3 className="mb-2">Event timeline</h3>
                <LemonTable
                    columns={eventColumns}
                    dataSource={execution.events || []}
                    emptyState="No events"
                    size="small"
                />
            </SceneContent>
        </>
    )
}
