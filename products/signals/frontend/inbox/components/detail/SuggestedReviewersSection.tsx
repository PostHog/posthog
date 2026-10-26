import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { userLogic } from 'scenes/userLogic'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { EnrichedReviewer, SignalReport } from '../../types'
import { openRemoveReviewerDialog } from './RemoveReviewerDialog'
import { getReviewerDisplayName } from './reviewerDisplay'
import { removeSuggestedReviewers, ReviewerSearchList } from './ReviewerSearchList'
import { SuggestedReviewersSectionView } from './SuggestedReviewersSectionView'

export function SuggestedReviewersSection({ report }: { report: SignalReport }): JSX.Element | null {
    const logic = inboxReportDetailLogic({ reportId: report.id, report })
    const { displayReviewers, isUpdatingReviewers, reportArtefacts, reportClaimant, isReportClaimable, claimSaving } =
        useValues(logic)
    const { updateReviewers, setReportClaimed } = useActions(logic)
    const { user } = useValues(userLogic)

    const [addOpen, setAddOpen] = useState(false)
    const baseReviewers = displayReviewers ?? []

    // Wait for the artefact log to load before rendering, so we don't flash an empty state that then
    // fills in. Once loaded, always render — a report with zero reviewers still shows the "Add" affordance
    // so a reviewer can be assigned from scratch.
    if (reportArtefacts === null) {
        return null
    }

    // The row's remove button asks why first, because a reason is what lets research route the next
    // similar report better. The picker's untoggle stays a one-click edit.
    const removeReviewers = (targets: EnrichedReviewer[]): void =>
        openRemoveReviewerDialog({
            reviewerName: targets.map(getReviewerDisplayName).join(', '),
            isSelf: !!user?.uuid && targets.every((target) => (target.user?.uuid ?? target.user_uuid) === user.uuid),
            onConfirm: (removal) =>
                removeSuggestedReviewers({
                    report,
                    surface: 'detail_pane',
                    targets,
                    reviewers: baseReviewers,
                    updateReviewers,
                    removal,
                }),
        })

    return (
        <SuggestedReviewersSectionView
            reviewers={baseReviewers}
            disabled={isUpdatingReviewers}
            onRemove={removeReviewers}
            claim={{
                claimantUuid: reportClaimant?.uuid ?? null,
                currentUserUuid: user?.uuid ?? null,
                claimable: isReportClaimable,
                saving: claimSaving,
                onSetClaimed: setReportClaimed,
            }}
            addControl={
                <LemonDropdown
                    visible={addOpen}
                    onClickOutside={() => setAddOpen(false)}
                    closeOnClickInside={false}
                    placement="bottom-end"
                    overlay={<ReviewerSearchList report={report} surface="detail_pane" />}
                >
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconPlus />}
                        disabledReason={isUpdatingReviewers ? 'Updating…' : undefined}
                        onClick={() => setAddOpen((open) => !open)}
                    >
                        Add Reviewer
                    </LemonButton>
                </LemonDropdown>
            }
        />
    )
}
