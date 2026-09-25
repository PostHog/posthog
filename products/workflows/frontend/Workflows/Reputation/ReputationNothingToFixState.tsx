import { useValues } from 'kea'

import * as lifeguardPng from '@posthog/brand/hoggies/png/lifeguard'
import { LemonCard } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'

import { workflowsReputationActionsLogic } from './workflowsReputationActionsLogic'

const HedgehogLifeguard = pngHoggie(lifeguardPng)

export function ReputationNothingToFixState(): JSX.Element {
    const { awsReputation, hasJudgedProviders } = useValues(workflowsReputationActionsLogic)
    return (
        <LemonCard
            hoverEffect={false}
            className="flex flex-col items-center text-center gap-2 px-4 py-8"
            data-attr="workflows-reputation-nothing-to-fix"
        >
            {/* The hover tilt is a small easter egg: the lifeguard scans the water with its binoculars. */}
            <HedgehogLifeguard className="w-28 motion-safe:transition-transform motion-safe:duration-300 motion-safe:hover:-rotate-6 motion-safe:hover:-translate-y-1" />
            <h2 className="text-base font-semibold mb-0">Nothing to rescue right now</h2>
            <p className="text-secondary max-w-120 mb-0">
                {awsReputation
                    ? 'Your email provider has not flagged anything, and no workflow with enough email to judge is over the bounce or spam complaint lines.'
                    : 'No workflow with enough email to judge is over the bounce or spam complaint lines.'}
                {hasJudgedProviders && ' Every mailbox provider with enough data is under the bounce line too.'}
            </p>
            <p className="text-secondary text-xs mb-0">
                The lifeguard stays on duty. If a workflow's email gets paused, we email your project admins.
            </p>
        </LemonCard>
    )
}
