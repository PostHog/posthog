// PROTOTYPE (branch prototype/sending-limits-ux): the recipients step's answers to who gets it, when it
// finishes and why, plus the route to ask for more. Every variant shows them in its own words. Never merge.
import { ReactNode } from 'react'

import { Link } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { AskForMore } from './AskForMore'
import { SendPlan } from './sendPlan'

interface PlanAnswersProps {
    plan: SendPlan
    why: ReactNode
    // Set when nothing can go out, for example "sending is paused".
    paused?: string
}

function Answer({ label, children }: { label: string; children: ReactNode }): JSX.Element {
    return (
        <div className="flex gap-3 text-sm">
            <span className="w-28 shrink-0 text-secondary">{label}</span>
            <span>{children}</span>
        </div>
    )
}

export function PlanAnswers({ plan, why, paused }: PlanAnswersProps): JSX.Element {
    const first = plan.days[0]?.emails ?? 0
    return (
        <div className="flex flex-col gap-1.5 border-t pt-3">
            <Answer label="Who gets it">
                {paused ? 'Nobody yet.' : 'Everyone in this audience. Nobody is left out.'}
            </Answer>
            <Answer label="When it's done">
                {paused
                    ? `Nothing goes out while ${paused}.`
                    : plan.finish === 'today'
                      ? 'Today.'
                      : `${humanFriendlyNumber(first)} people today, everyone by ${plan.finish}.`}
            </Answer>
            <Answer label="Why">{why}</Answer>
            <div className="text-sm text-secondary">
                {paused ? (
                    <>
                        Think this is wrong? <Link>Contact support</Link>.
                    </>
                ) : (
                    <AskForMore />
                )}
            </div>
        </div>
    )
}
