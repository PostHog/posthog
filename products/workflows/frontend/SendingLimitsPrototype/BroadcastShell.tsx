// PROTOTYPE (branch prototype/sending-limits-ux): stand-ins for the broadcast wizard's recipients step
// and the broadcast page after launch, never merge.
import { ReactNode } from 'react'

import { LemonButton, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { SendingState } from './sendingLimitsPrototypeData'

interface BroadcastShellProps {
    state: SendingState
    recipientsHint?: ReactNode
    launchDisabledReason?: string
    status: { label: string; type: LemonTagType }
    afterLaunch: ReactNode
}

export function BroadcastShell({
    state,
    recipientsHint,
    launchDisabledReason,
    status,
    afterLaunch,
}: BroadcastShellProps): JSX.Element {
    const { broadcast } = state
    return (
        <div className="flex flex-col gap-6 max-w-200 mx-auto">
            <section className="flex flex-col gap-2">
                <span className="text-xs uppercase text-secondary font-semibold">Recipients step, before launch</span>
                <div className="border rounded p-4 bg-surface-primary flex flex-col gap-3">
                    <div className="font-semibold">Who should get it?</div>
                    <div className="border rounded px-3 py-2 text-secondary">Cohort: Newsletter subscribers</div>
                    <div className="text-muted">
                        approximately {humanFriendlyNumber(broadcast.audience)} of{' '}
                        {humanFriendlyNumber(Math.round(broadcast.audience * 1.25))} people.
                    </div>
                    {recipientsHint}
                    <div className="flex justify-end">
                        <LemonButton type="primary" disabledReason={launchDisabledReason}>
                            Launch broadcast
                        </LemonButton>
                    </div>
                </div>
            </section>
            <section className="flex flex-col gap-2">
                <span className="text-xs uppercase text-secondary font-semibold">Broadcast page, after launch</span>
                <div className="border rounded p-4 bg-surface-primary flex flex-col gap-3">
                    <div className="flex items-center gap-2">
                        <h3 className="m-0">{broadcast.name}</h3>
                        <LemonTag type={status.type}>{status.label}</LemonTag>
                    </div>
                    {afterLaunch}
                </div>
            </section>
        </div>
    )
}
