import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { ReputationActionRow } from './ReputationActionRow'
import { ReputationNothingToFixState } from './ReputationNothingToFixState'
import { actionStyle } from './reputationUtils'
import { workflowsReputationActionsLogic } from './workflowsReputationActionsLogic'

const COLLAPSED_COUNT = 5

export function ReputationActionList(): JSX.Element {
    const { reputationActions, showAllActions } = useValues(workflowsReputationActionsLogic)
    const { toggleShowAllActions } = useActions(workflowsReputationActionsLogic)
    // Collapse only when at least two rows would be hidden. Hiding one row saves no space over
    // showing it.
    const canCollapse = reputationActions.length > COLLAPSED_COUNT + 1
    const visibleActions =
        canCollapse && !showAllActions ? reputationActions.slice(0, COLLAPSED_COUNT) : reputationActions
    const hiddenCount = reputationActions.length - COLLAPSED_COUNT

    if (reputationActions.length === 0) {
        return <ReputationNothingToFixState />
    }

    return (
        <LemonCard hoverEffect={false} className="p-0 @container" data-attr="workflows-reputation-actions">
            <div className="px-4 py-3 border-b">
                <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-base font-semibold mb-0">Improve your sending reputation</h2>
                    <LemonTag type={actionStyle(reputationActions[0]).tagType}>
                        {pluralize(reputationActions.length, 'item')}
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
        </LemonCard>
    )
}
