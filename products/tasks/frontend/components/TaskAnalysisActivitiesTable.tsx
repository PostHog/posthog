import { LemonTable } from '@posthog/lemon-ui'

import type { TaskRunAnalysisActivityRequestApi } from '../generated/api.schemas'

export function TaskAnalysisActivitiesTable({
    activities,
}: {
    activities: TaskRunAnalysisActivityRequestApi[]
}): JSX.Element {
    return (
        <LemonTable
            embedded
            size="small"
            dataSource={activities}
            rowKey={(activity) => `${activity.start_line}-${activity.end_line}`}
            columns={[
                { title: 'Goal', dataIndex: 'goal_kind' },
                {
                    title: 'Description',
                    dataIndex: 'goal',
                    render: (_, activity: TaskRunAnalysisActivityRequestApi) => (
                        <span className="break-words">{activity.goal}</span>
                    ),
                },
                { title: 'Outcome', dataIndex: 'outcome' },
                {
                    title: 'Blocker',
                    dataIndex: 'blocker_kind',
                    render: (_, activity: TaskRunAnalysisActivityRequestApi) =>
                        activity.blocker_kind
                            ? [activity.blocker_kind, activity.blocker_name].filter(Boolean).join(': ')
                            : null,
                },
                { title: 'Tool calls', dataIndex: 'tool_calls', align: 'right' },
                { title: 'Seconds', dataIndex: 'seconds', align: 'right' },
            ]}
        />
    )
}
