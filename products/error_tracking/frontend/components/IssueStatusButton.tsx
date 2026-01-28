import { LemonButton, LemonMenuOverlay } from '@posthog/lemon-ui'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { STATUS_INTENT_LABEL } from './Indicators'

export const IssueStatusButton = ({
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
            tooltip={status === 'active' ? STATUS_INTENT_LABEL['resolved'] : STATUS_INTENT_LABEL['active']}
            data-attr="error-tracking-resolve"
            sideAction={
                status === 'active'
                    ? {
                          dropdown: {
                              placement: 'bottom-end',
                              overlay: (
                                  <LemonMenuOverlay
                                      items={[
                                          {
                                              label: 'Suppress',
                                              onClick: () => onChange('suppressed'),
                                              tooltip: STATUS_INTENT_LABEL['suppressed'],
                                          },
                                      ]}
                                  />
                              ),
                          },
                      }
                    : undefined
            }
            size="small"
        >
            {status === 'active' ? 'Resolve' : 'Reopen'}
        </LemonButton>
    )
}
