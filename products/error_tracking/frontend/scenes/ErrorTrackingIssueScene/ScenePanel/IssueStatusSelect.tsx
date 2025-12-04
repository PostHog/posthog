import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

export const IssueStatusSelect = ({
    status,
    onChange,
}: {
    status: ErrorTrackingIssue['status']
    onChange: (status: ErrorTrackingIssue['status']) => void
}): JSX.Element => {
    return (
        <LemonButton
            type="primary"
            onClick={() => onChange(status === 'active' ? 'resolved' : 'active')}
            sideAction={
                status === 'active'
                    ? {
                          icon: <IconX />,
                          tooltip: 'Suppress issue',
                          onClick: () => onChange('suppressed'),
                      }
                    : undefined
            }
        >
            {status === 'active' ? 'Resolve' : 'Reopen'}
        </LemonButton>
    )
}
