import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { LabelIndicator, StatusIndicator } from '../Indicators'
import { issueQueryOptionsLogic } from '../IssueQueryOptions/issueQueryOptionsLogic'

type Option = ErrorTrackingIssue['status'] | 'all' | null

export const StatusFilter = (): JSX.Element => {
    const { status } = useValues(issueQueryOptionsLogic)
    const { setStatus } = useActions(issueQueryOptionsLogic)

    const label = (key: Option) => {
        switch (key) {
            case 'all':
            case null:
                return <LabelIndicator intent="muted" label="All" size="small" />
            default:
                return <StatusIndicator status={key} size="small" />
        }
    }

    const options: Option[] = ['all', 'active', 'resolved', 'suppressed']

    return (
        <LemonSelect
            onChange={(value) => setStatus(value || undefined)}
            value={status || null}
            placeholder="Select status"
            options={options.map((key) => ({
                value: key,
                label: label(key),
            }))}
            size="small"
        />
    )
}
