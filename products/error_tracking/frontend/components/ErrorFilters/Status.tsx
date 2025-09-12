import { useActions, useValues } from 'kea'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { GenericSelect } from '../GenericSelect'
import { LabelIndicator, StatusIndicator } from '../Indicator'
import { issueQueryOptionsLogic } from '../IssueQueryOptions/issueQueryOptionsLogic'

export const StatusFilter = (): JSX.Element => {
    const { status } = useValues(issueQueryOptionsLogic)
    const { setStatus } = useActions(issueQueryOptionsLogic)

    return (
        <GenericSelect<ErrorTrackingIssue['status'] | 'all' | null>
            values={['all', 'active', 'resolved', 'suppressed']}
            current={status || null}
            renderValue={(key) => {
                switch (key) {
                    case 'all':
                    case null:
                        return <LabelIndicator intent="muted" label="All" size="small" />
                    default:
                        return <StatusIndicator status={key} size="small" />
                }
            }}
            placeholder="Select status"
            onChange={(value) => setStatus(value || undefined)}
            size="small"
        />
    )
}
