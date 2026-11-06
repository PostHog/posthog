import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { selfDrivingTrialLogic } from '../../logics/selfDrivingTrialLogic'

export function SelfDrivingTrialUsage(): JSX.Element | null {
    const { currentTeamId } = useValues(teamLogic)
    const logic = selfDrivingTrialLogic({ teamId: currentTeamId! })
    const { trial, trialLoading, error } = useValues(logic)
    const { loadTrial } = useActions(logic)

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
    const continuation = {
        continue_paid: 'New work continues under your existing paid Self-driving limit.',
        add_payment_method: 'New work pauses until you add a payment method and enable paid Self-driving.',
        increase_limit:
            'New work pauses until your Self-driving spending limit permits it. You can increase the limit in billing.',
        enable_self_driving: 'New work pauses until you enable paid Self-driving.',
        unavailable: 'Billing status is unavailable. New work will pause if paid authorization cannot be confirmed.',
    }[trial.paid_continuation]

    return (
        <section className="min-w-0" aria-label="Self-driving free trial">
            <LemonBanner type={exhausted ? 'warning' : 'info'}>
                <div className="flex flex-col gap-2 min-w-0 font-normal">
                    <strong>{exhausted ? 'Trial limit reached' : 'Your Self-driving free trial'}</strong>
                    <p className="m-0">
                        <span>{`${trial.reports_delivered} of ${trial.report_limit} reports delivered`}</span>
                        {!!trial.reports_in_progress && <span>{` · ${trial.reports_in_progress} in progress`}</span>}
                        {' · '}
                        <span>{`${trial.enabled_scouts}${!exhausted ? ` of ${trial.scout_limit}` : ''} scouts enabled`}</span>
                    </p>
                    <LemonProgress
                        percent={(100 * trial.used_microusd) / trial.allowance_microusd}
                        aria-label="Trial allowance used"
                    />
                    <p className="m-0">
                        {`$${(trial.used_microusd / 1_000_000).toFixed(2)} of $${trial.allowance_microusd / 1_000_000} trial allowance used.`}
                    </p>
                    {exhausted && (
                        <p className="m-0">
                            <span>
                                {trial.exhaustion_reason === 'report_limit'
                                    ? 'The trial report limit has been reached, including reports still in progress.'
                                    : 'The trial allowance is exhausted.'}
                            </span>{' '}
                            <span>Work already underway can finish at no additional charge. {continuation}</span>
                        </p>
                    )}
                    {exhausted && trial.new_work_paused && (
                        <LemonButton className="self-start" type="primary" to={urls.organizationBilling()}>
                            {trial.paid_continuation === 'increase_limit'
                                ? 'Increase Self-driving limit'
                                : trial.paid_continuation === 'add_payment_method'
                                  ? 'Add payment method'
                                  : 'Manage billing'}
                        </LemonButton>
                    )}
                </div>
            </LemonBanner>
        </section>
    )
}
