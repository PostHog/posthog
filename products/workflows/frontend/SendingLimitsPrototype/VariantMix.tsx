// PROTOTYPE (branch prototype/sending-limits-ux): the mix of B, C and D. Sender setup is D's domain
// check, the broadcast is C's plan, and the Reputation page shows all three above the fix list. Never merge.
import { Link } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { ActionListShell } from './ActionListShell'
import { DOMAIN_CHECKS, DomainProfileKey, SendingState, SurfaceKey } from './sendingLimitsPrototypeData'
import { BlockedBanner, WarmUpCard } from './VariantBExplain'
import { SendsInProgress, VariantCBroadcast } from './VariantCBroadcast'
import { DomainCheckCard, VariantDSetupCheck } from './VariantDSetupCheck'

interface VariantMixProps {
    surface: SurfaceKey
    state: SendingState
    domainProfile: DomainProfileKey
    setDomainProfile: (value: DomainProfileKey) => void
}

export function VariantMix({ surface, state, domainProfile, setDomainProfile }: VariantMixProps): JSX.Element {
    // A new sender's first broadcast depends on the domain check, so it uses D's view.
    if (surface === 'setup' || (surface === 'broadcast' && state.key === 'new')) {
        return (
            <VariantDSetupCheck
                surface={surface}
                state={state}
                domainProfile={domainProfile}
                setDomainProfile={setDomainProfile}
            />
        )
    }
    if (surface === 'broadcast') {
        return <VariantCBroadcast surface={surface} state={state} />
    }

    // Only a new sender takes the picked domain. The later states' fake history starts at 1,000 a day,
    // which is the Starter band.
    const isNew = state.key === 'new'
    const check = isNew ? DOMAIN_CHECKS[domainProfile] : DOMAIN_CHECKS.starter
    const checkedOn = isNew ? 'Dec 10' : 'Dec 3'
    const start = check.startPerDay
    const shown: SendingState =
        isNew && start !== null
            ? {
                  ...state,
                  allowancePerDay: start,
                  moves: [{ ...state.moves[0], to: start, reason: check.verdict.split('. ')[0] + '.' }],
              }
            : state
    return (
        <ActionListShell
            renderKey={`Mix-${state.key}-${domainProfile}`}
            state={state}
            top={
                <>
                    {state.key === 'blocked' && <BlockedBanner state={state} />}
                    {start === null ? (
                        <DomainCheckCard check={check} checkedOn={checkedOn} />
                    ) : (
                        <WarmUpCard
                            state={shown}
                            startedFrom={
                                <>
                                    Started at {humanFriendlyNumber(start)} a day, set by{' '}
                                    {check.source === 'paid plan'
                                        ? 'your paid plan'
                                        : `the domain check (${check.band})`}{' '}
                                    on {checkedOn}. <Link>See the domain check</Link>.
                                </>
                            }
                        />
                    )}
                    <SendsInProgress state={state} />
                </>
            }
        />
    )
}
