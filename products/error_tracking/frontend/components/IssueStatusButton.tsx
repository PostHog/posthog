import { useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonButton, LemonMenuOverlay } from '@posthog/lemon-ui'

import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { ISSUE_STATUS_CONFIG } from './Indicators'
import { issueActionsLogic } from './IssueActions/issueActionsLogic'

export const IssueStatusButton = ({
    status,
    onChange,
}: {
    status: ErrorTrackingIssue['status']
    onChange: (status: ErrorTrackingIssue['status']) => void
}): JSX.Element => {
    const { trigger, HogfettiComponent } = useHogfetti()
    const { pendingMutations, resolveCelebrationNonce } = useValues(issueActionsLogic)

    const isUpdatingStatus = (pendingMutations['updateIssueStatus'] ?? 0) > 0

    // Celebrate when a resolve actually succeeds, not when the button is clicked.
    const triggerRef = useRef(trigger)
    triggerRef.current = trigger
    const lastNonceRef = useRef(resolveCelebrationNonce)
    useEffect(() => {
        if (resolveCelebrationNonce === lastNonceRef.current) {
            return
        }
        lastNonceRef.current = resolveCelebrationNonce
        const timers = [0, 400, 800].map((delay) => window.setTimeout(() => triggerRef.current(), delay))
        return () => timers.forEach((timer) => window.clearTimeout(timer))
    }, [resolveCelebrationNonce])

    const handleResolve = (): void => {
        onChange(status === 'active' ? 'resolved' : 'active')
    }

    return (
        <>
            <HogfettiComponent />
            <LemonButton
                type="primary"
                onClick={handleResolve}
                loading={isUpdatingStatus}
                tooltip={
                    status === 'active'
                        ? ISSUE_STATUS_CONFIG.resolved.intentLabel
                        : ISSUE_STATUS_CONFIG.active.intentLabel
                }
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
                                                  tooltip: ISSUE_STATUS_CONFIG.suppressed.intentLabel,
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
