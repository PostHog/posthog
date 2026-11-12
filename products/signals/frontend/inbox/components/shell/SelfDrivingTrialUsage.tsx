import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { selfDrivingTrialLogic } from '../../logics/selfDrivingTrialLogic'
import { formatCredits, usdToCredits } from '../../utils/credits'

export function SelfDrivingTrialUsage(): JSX.Element | null {
    const { currentTeamId } = useValues(teamLogic)
    const logic = selfDrivingTrialLogic({ teamId: currentTeamId! })
    const { trial, trialEnabled, trialLoading, error } = useValues(logic)
    const { loadTrial } = useActions(logic)

    if (!trialEnabled) {
        return null
    }
    if (error) {
        return (
            <div>
                <LemonBanner type="warning">
                    <div className="flex flex-wrap items-center gap-2">
                        <span>{error}</span>
                        <LemonButton
                            size="small"
                            loading={trialLoading}
                            onClick={loadTrial}
                            data-attr="self-driving-trial-retry"
                        >
                            Retry
                        </LemonButton>
                    </div>
                </LemonBanner>
            </div>
        )
    }
    if (!trial?.enabled || trial.grant_status === 'not_claimed') {
        return null
    }

    const exhausted = trial.grant_status === 'exhausted'
    const banner = exhausted
        ? { title: 'Trial limit reached', scoutCount: `${trial.enabled_scouts}` }
        : {
              title: 'Your Self-driving free trial',
              scoutCount: `${trial.enabled_scouts} of ${trial.scout_limit}`,
          }
    const continuation = {
        continue_paid: {
            message: 'New work continues under your existing paid Self-driving limit.',
            action: 'Manage billing',
        },
        add_payment_method: {
            message: 'New work pauses until you add a payment method and enable paid Self-driving.',
            action: 'Add payment method',
        },
        increase_limit: {
            message:
                'New work pauses until your Self-driving spending limit permits it. You can increase the limit in billing.',
            action: 'Increase Self-driving limit',
        },
        enable_self_driving: {
            message: 'New work pauses until you enable paid Self-driving.',
            action: 'Manage billing',
        },
        unavailable: {
            message: 'Billing status is unavailable. New work will pause if paid authorization cannot be confirmed.',
            action: 'Manage billing',
        },
    }[trial.paid_continuation]

    const content = (
        <div className="flex flex-col gap-2 min-w-0 font-normal">
            <strong className="text-sm font-semibold">{banner.title}</strong>
            <p className="m-0 text-sm">
                <span>{`${trial.reports_delivered} of ${trial.report_limit} reports delivered`}</span>
                {!!trial.reports_in_progress && <span>{` · ${trial.reports_in_progress} in progress`}</span>}
                {' · '}
                <span>{`${banner.scoutCount} scouts enabled`}</span>
            </p>
            <LemonProgress
                percent={(100 * trial.used_microusd) / trial.allowance_microusd}
                aria-label="Trial allowance used"
            />
            <p className="m-0 text-xs text-secondary">
                {`Trial allowance used: ${formatCredits(usdToCredits(trial.used_microusd / 1_000_000))} of ${formatCredits(usdToCredits(trial.allowance_microusd / 1_000_000))}.`}
            </p>
            {exhausted && (
                <p className="m-0">
                    <span>
                        {trial.exhaustion_reason === 'report_limit'
                            ? 'The trial report limit has been reached, including reports still in progress.'
                            : 'The trial allowance is exhausted.'}
                    </span>{' '}
                    <span>Work already underway can finish at no additional charge. {continuation.message}</span>
                </p>
            )}
            {exhausted && trial.new_work_paused && (
                <LemonButton className="self-start" type="primary" to={urls.organizationBilling()}>
                    {continuation.action}
                </LemonButton>
            )}
        </div>
    )

    return (
        <section
            className={exhausted ? 'min-w-0' : 'min-w-0 border-t border-primary pt-3'}
            aria-label="Self-driving free trial"
        >
            {exhausted ? <LemonBanner type="warning">{content}</LemonBanner> : content}
        </section>
    )
}
