import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { reviewerExclusionsLogic } from '../../logics/reviewerExclusionsLogic'
import { reviewerExclusionAreaLabel } from '../../utils/reviewerExclusionAreas'
import { AutonomySettingRow } from './AutonomySettingRow'

/** Lists the areas where automatic reviewer selection skips the current user, so each can be undone. */
export function ReviewerExclusionsRow(): JSX.Element {
    const { exclusions, exclusionsLoading, revokingIds } = useValues(reviewerExclusionsLogic)
    const { revokeExclusion } = useActions(reviewerExclusionsLogic)

    return (
        <AutonomySettingRow
            title="Areas you stay off"
            description="Automatic reviewer picks skip you for reports in these areas of this project. Add one when you remove yourself from a report."
        >
            {exclusions === null && exclusionsLoading ? (
                <LemonSkeleton className="h-6 w-full rounded" />
            ) : !exclusions?.length ? (
                <span className="py-3 text-xs text-secondary">None yet.</span>
            ) : (
                exclusions.map((exclusion) => (
                    <div key={exclusion.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                        <div className="flex min-w-0 flex-1 basis-48 flex-col">
                            <span className="truncate text-sm text-default">
                                {exclusion.repository
                                    ? reviewerExclusionAreaLabel({
                                          repository: exclusion.repository,
                                          pathPrefix: exclusion.path_prefix,
                                      })
                                    : 'Every repository'}
                            </span>
                            <span className="truncate text-xs text-secondary">{exclusion.instruction}</span>
                        </div>
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            loading={revokingIds.includes(exclusion.id)}
                            onClick={() => revokeExclusion(exclusion.id)}
                            data-attr="signals-reviewer-exclusion-revoke"
                        >
                            Remove
                        </LemonButton>
                    </div>
                ))
            )}
        </AutonomySettingRow>
    )
}
