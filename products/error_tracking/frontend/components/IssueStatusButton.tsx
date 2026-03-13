import { LemonButton, LemonMenuOverlay } from '@posthog/lemon-ui'

import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { STATUS_INTENT_LABEL } from './Indicators'

export const IssueStatusButton = ({
    status,
    onChange,
}: {
    status: ErrorTrackingIssue['status']
    onChange: (status: ErrorTrackingIssue['status']) => void
}): JSX.Element => {
    const { trigger, HogfettiComponent } = useHogfetti()

    const handleResolve = (): void => {
        if (status === 'active') {
            onChange('resolved')
            ;[0, 400, 800].forEach((delay) => setTimeout(trigger, delay))
        } else {
            onChange('active')
        }
    }

    return (
        <>
            <HogfettiComponent />
            <LemonButton
                type="primary"
                onClick={handleResolve}
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
        </>
    )
}
