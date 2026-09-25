import { useActions, useValues } from 'kea'

import * as partyPng from '@posthog/brand/hoggies/png/party'
import { LemonButton, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'

import { ReputationActionRow } from './ReputationActionRow'
import type { ReputationActionSeverity } from './reputationActions'
import { workflowsReputationLogic } from './workflowsReputationLogic'

const HedgehogParty = pngHoggie(partyPng)

const COLLAPSED_COUNT = 5

const COUNT_TAG_TYPE: Record<ReputationActionSeverity, LemonTagType> = {
    high: 'danger',
    medium: 'warning',
    low: 'muted',
}

export function ReputationActionList(): JSX.Element {
    const { reputationActions, showAllActions, awsReputation, ispSendingHealth } = useValues(workflowsReputationLogic)
    const { toggleShowAllActions } = useActions(workflowsReputationLogic)
    // Collapse only when at least two rows would be hidden. Hiding one row saves no space over
    // showing it.
    const canCollapse = reputationActions.length > COLLAPSED_COUNT + 1
    const visibleActions =
        canCollapse && !showAllActions ? reputationActions.slice(0, COLLAPSED_COUNT) : reputationActions
    const hiddenCount = reputationActions.length - COLLAPSED_COUNT

    if (reputationActions.length === 0) {
        return (
            <section
                className="border rounded bg-surface-primary flex flex-col items-center text-center gap-2 px-4 py-8"
                data-attr="workflows-reputation-nothing-to-fix"
            >
                <HedgehogParty className="w-32" />
                <h2 className="text-base font-semibold mb-0">Nothing to fix right now</h2>
                <p className="text-secondary max-w-120 mb-0">
                    {awsReputation
                        ? 'Your email provider has not flagged anything, and no workflow is over the bounce or spam complaint lines.'
                        : 'No workflow is over the bounce or spam complaint lines.'}
                    {ispSendingHealth.length > 0 && ' Every mailbox provider is under the bounce line too.'}
                </p>
            </section>
        )
    }

    return (
        <section className="border rounded bg-surface-primary @container" data-attr="workflows-reputation-actions">
            <div className="px-4 py-3 border-b">
                <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-base font-semibold mb-0">Improve your sending reputation</h2>
                    <LemonTag type={COUNT_TAG_TYPE[reputationActions[0].severity]}>
                        {`${reputationActions.length} ${reputationActions.length === 1 ? 'item' : 'items'}`}
                    </LemonTag>
                </div>
                <p className="text-secondary mb-0 mt-1">
                    Work through these from the top to lower your bounce and spam complaint rates.
                </p>
            </div>
            {/* list-none drops list semantics in Safari, and the role restores them. */}
            <ol className="list-none m-0 p-0" role="list">
                {visibleActions.map((action, index) => (
                    <ReputationActionRow key={action.key} action={action} position={index + 1} />
                ))}
            </ol>
            {canCollapse && (
                <div className="border-t p-1">
                    <LemonButton
                        fullWidth
                        center
                        size="small"
                        onClick={toggleShowAllActions}
                        data-attr="workflows-reputation-actions-toggle"
                    >
                        {showAllActions ? 'Show fewer' : `Show ${hiddenCount} more`}
                    </LemonButton>
                </div>
            )}
        </section>
    )
}
