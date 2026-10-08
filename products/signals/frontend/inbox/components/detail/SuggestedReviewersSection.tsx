import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { EnrichedReviewer, SignalReport } from '../../types'
import { removeSuggestedReviewers, ReviewerSearchList } from './ReviewerSearchList'
import { SuggestedReviewersSectionView } from './SuggestedReviewersSectionView'

export function SuggestedReviewersSection({ report }: { report: SignalReport }): JSX.Element | null {
    const logic = inboxReportDetailLogic({ reportId: report.id, report })
    const { displayReviewers, isUpdatingReviewers, reportArtefacts } = useValues(logic)
    const { updateReviewers } = useActions(logic)

    const [addOpen, setAddOpen] = useState(false)
    const baseReviewers = displayReviewers ?? []

    // Wait for the artefact log to load before rendering, so we don't flash an empty state that then
    // fills in. Once loaded, always render — a report with zero reviewers still shows the "Add" affordance
    // so a reviewer can be assigned from scratch.
    if (reportArtefacts === null) {
        return null
    }

    const removeReviewers = (targets: EnrichedReviewer[]): void =>
        removeSuggestedReviewers({
            report,
            surface: 'detail_pane',
            targets,
            reviewers: baseReviewers,
            updateReviewers,
        })

    return (
        <SuggestedReviewersSectionView
            reviewers={baseReviewers}
            disabled={isUpdatingReviewers}
            onRemove={removeReviewers}
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
