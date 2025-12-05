import { LemonButton, LemonMenuOverlay } from '@posthog/lemon-ui'

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
            sideAction={{
                dropdown: {
                    placement: 'bottom-end',
                    overlay: (
                        <LemonMenuOverlay
                            items={[
                                status !== 'suppressed'
                                    ? {
                                          label: 'Suppress issue',
                                          onClick: () => onChange('suppressed'),
                                      }
                                    : {
                                          label: 'Stop suppressing, but keep resolved',
                                          onClick: () => onChange('resolved'),
                                      },
                            ]}
                        />
                    ),
                },
            }}
            size="small"
        >
            {status === 'active' ? 'Resolve' : 'Reopen'}
        </LemonButton>
    )
}
