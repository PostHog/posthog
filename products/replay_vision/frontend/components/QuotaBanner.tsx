import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { urls } from 'scenes/urls'

import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { formatCreditsRange } from '../utils/credits'
import { quotaBannerState } from '../utils/quotaProjection'

/**
 * Warns before, and explains after, scanning stops for the period, always with a way out.
 * Assumes block-only overage policy; revisit when `usage_based` ships so we don't scare metered orgs.
 */
export function QuotaBanner(): JSX.Element | null {
    const { quota, quotaLoading, canRaiseCreditLimit } = useValues(visionQuotaLogic)
    const { raiseCreditLimit } = useActions(visionQuotaLogic)
    const { openSupportForm } = useActions(supportLogic)

    const state = quotaBannerState(quota)
    if (!state.kind) {
        return null
    }
    const exhausted = state.kind === 'exhausted'
    const spend = formatCreditsRange(state.quota.credits_used, state.quota.credit_limit ?? 0)

    return (
        <LemonBanner type={exhausted ? 'error' : 'warning'}>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span>
                    {exhausted
                        ? `Replay vision budget used up: ${spend}. Scanning is paused until ${state.resetsOn}.`
                        : `You've used ${spend} of your Replay vision budget. Scanning pauses if you reach the limit. Your budget resets ${state.resetsOn}.`}
                </span>
                {state.quota.billing_managed ? (
                    <Link to={urls.organizationBilling()}>Change your spend limit</Link>
                ) : canRaiseCreditLimit ? (
                    <>
                        <span>You aren't billed for Replay vision during the closed beta.</span>
                        <LemonButton
                            size="small"
                            type="secondary"
                            loading={quotaLoading}
                            onClick={() => raiseCreditLimit()}
                            data-attr="vision-quota-raise-limit"
                        >
                            Raise budget
                        </LemonButton>
                    </>
                ) : state.quota.can_raise_credit_limit ? (
                    <span>Ask an organization admin to raise the budget.</span>
                ) : (
                    <>
                        <span>This is the highest budget you can set yourself.</span>
                        <Link
                            onClick={() =>
                                openSupportForm({
                                    kind: 'support',
                                    target_area: 'session_replay',
                                    message: 'I need a higher Replay vision budget for this period.\n\n',
                                })
                            }
                        >
                            Ask us for more
                        </Link>
                    </>
                )}
            </div>
        </LemonBanner>
    )
}
