import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { userLogic } from 'scenes/userLogic'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { EnrichedReviewer, ReviewerRemoval, SignalReport } from '../../types'
import { QuillReviewerSearchList } from './QuillReviewerSearchList'
import { QuillSuggestedReviewersSectionView } from './QuillSuggestedReviewersSectionView'
import { removeSuggestedReviewers } from './suggestedReviewers'

/** The quill sibling of `SuggestedReviewersSection`, for the report page behind `today-rail-nav`. */
export function QuillSuggestedReviewersSection({ report }: { report: SignalReport }): JSX.Element | null {
    const logic = inboxReportDetailLogic({ reportId: report.id, report })
    const { displayReviewers, isUpdatingReviewers, reportArtefacts, reportClaimant, isReportClaimable, claimSaving } =
        useValues(logic)
    const { updateReviewers, setReportClaimed } = useActions(logic)
    const { user } = useValues(userLogic)

    const baseReviewers = displayReviewers ?? []

    // Wait for the artefact log to load, so an empty state does not flash and then fill in. A report with
    // zero reviewers still shows "Add Reviewer", so a reviewer can be assigned from scratch.
    if (reportArtefacts === null) {
        return null
    }

    const removeReviewers = (targets: EnrichedReviewer[], removal?: ReviewerRemoval): void =>
        removeSuggestedReviewers({
            report,
            surface: 'detail_pane',
            targets,
            reviewers: baseReviewers,
            updateReviewers,
            removal,
        })

    return (
        <QuillSuggestedReviewersSectionView
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
                <QuillReviewerSearchList
                    report={report}
                    surface="detail_pane"
                    trigger={
                        <Button variant="outline" disabledReason={isUpdatingReviewers ? 'Updating…' : undefined}>
                            <IconPlus />
                            Add Reviewer
                        </Button>
                    }
                />
            }
        />
    )
}
