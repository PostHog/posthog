import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { selfDrivingTrialLogic } from '../logics/selfDrivingTrialLogic'

export function SelfDrivingTrialBanner(): JSX.Element | null {
    const { currentTeamId } = useValues(teamLogic)
    const logic = selfDrivingTrialLogic({ teamId: currentTeamId! })
    const { trial, trialLoading, error } = useValues(logic)
    const { loadTrial, activateTrial } = useActions(logic)

    if (error && trial?.enabled) {
        return (
            <div className="px-6 py-3">
                <LemonBanner type="warning">
                    <div className="flex flex-wrap items-center gap-2">
                        <span>{error}</span>
                        <LemonButton size="small" loading={trialLoading} onClick={loadTrial}>
                            Retry
                        </LemonButton>
                    </div>
                </LemonBanner>
            </div>
        )
    }
    if (!trial?.enabled || (!trial.billing_ready && trial.grant_status === 'not_claimed')) {
        return null
    }

    const offered = trial.grant_status === 'not_claimed'
    const exhausted = trial.grant_status === 'exhausted'
    const pending = trial.grant_status === 'pending'
    const continuation = {
        continue_paid: 'After the trial, new work continues under your existing paid Self-driving limit.',
        add_payment_method:
            'After the trial, new work pauses until you add a payment method and enable paid Self-driving.',
        increase_limit:
            'After the trial, new work pauses until your Self-driving spending limit permits it. You can increase the limit in billing.',
        enable_self_driving: 'After the trial, new work pauses until you enable paid Self-driving.',
        unavailable: 'Billing status is unavailable. New work will pause if paid authorization cannot be confirmed.',
    }[trial.paid_continuation]

    return (
        <section className="px-6 py-3 min-w-0" aria-label="Self-driving free trial">
            <LemonBanner type={exhausted ? 'warning' : 'info'}>
                <div className="flex flex-col gap-2 min-w-0 font-normal">
                    <strong>
                        {offered
                            ? 'Try Self-driving for free'
                            : exhausted
                              ? 'Your free trial is complete'
                              : pending
                                ? 'Your trial activation is pending'
                                : 'Your Self-driving free trial'}
                    </strong>
                    {offered ? (
                        <>
                            <p className="m-0">
                                Get a one-time $10 trial allowance for this project, with up to five reports and three
                                enabled scouts. The allowance may run out before five reports. It does not renew.
                            </p>
                            <p className="m-0">
                                Your organization can claim a trial for up to three projects. Environments share their
                                project's trial.
                            </p>
                            {trial.scouts_to_pause > 0 && (
                                <p className="m-0">
                                    Starting keeps your three oldest enabled scouts and pauses {trial.scouts_to_pause}{' '}
                                    others. You can swap which scouts are enabled.
                                </p>
                            )}
                            <p className="m-0">
                                {continuation} Starting the trial does not change your spending limit or enable
                                automatic PR creation.
                            </p>
                            <LemonButton
                                type="primary"
                                className="self-start"
                                loading={trialLoading}
                                disabledReason={
                                    !trial.can_activate
                                        ? 'Project management permission is required.'
                                        : !trial.eligible
                                          ? trial.organization_grants_remaining === 0
                                              ? 'Your organization has claimed all three lifetime trials.'
                                              : 'Trial activation is currently unavailable.'
                                          : undefined
                                }
                                onClick={activateTrial}
                            >
                                Start free trial
                            </LemonButton>
                        </>
                    ) : (
                        <>
                            <p className="m-0">
                                {trial.reports_delivered} of {trial.report_limit} reports delivered ·{' '}
                                {trial.enabled_scouts}
                                {!exhausted && ` of ${trial.scout_limit}`} scouts enabled
                            </p>
                            <LemonProgress
                                percent={(100 * trial.used_microusd) / trial.allowance_microusd}
                                aria-label="Trial allowance used"
                            />
                            <p className="m-0">
                                ${(trial.used_microusd / 1_000_000).toFixed(2)} of $10 trial allowance used.
                            </p>
                            {exhausted && (
                                <p className="m-0">
                                    {trial.exhaustion_reason === 'report_limit'
                                        ? 'All five trial reports have been delivered.'
                                        : 'The trial allowance is exhausted.'}{' '}
                                    Research already running can finish and publish its report. {continuation}
                                </p>
                            )}
                            {pending && (
                                <LemonButton
                                    className="self-start"
                                    loading={trialLoading}
                                    disabledReason={
                                        !trial.can_activate ? 'Project management permission is required.' : undefined
                                    }
                                    onClick={activateTrial}
                                >
                                    Retry activation
                                </LemonButton>
                            )}
                            {exhausted && trial.paid_continuation !== 'continue_paid' && (
                                <LemonButton className="self-start" type="primary" to={urls.organizationBilling()}>
                                    {trial.paid_continuation === 'increase_limit'
                                        ? 'Increase Self-driving limit'
                                        : trial.paid_continuation === 'add_payment_method'
                                          ? 'Add payment method'
                                          : 'Manage billing'}
                                </LemonButton>
                            )}
                        </>
                    )}
                </div>
            </LemonBanner>
        </section>
    )
}
