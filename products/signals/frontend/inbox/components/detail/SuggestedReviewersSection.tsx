import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconInfo, IconPeople, IconPlus } from '@posthog/icons'
import { LemonButton, Spinner, Tooltip } from '@posthog/lemon-ui'

import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { EnrichedReviewer, SignalReport } from '../../types'
import { DetailSection } from './DetailSection'
import { removeSuggestedReviewers, ReviewerSearchList } from './ReviewerSearchList'
import { SuggestedReviewersList } from './SuggestedReviewersList'

/**
 * Suggested reviewers for the report, read from the `suggested_reviewers` artefact, with add/remove
 * editing. Mirrors desktop's `SuggestedReviewersSection`: a search popover to add org members (current
 * user pinned "Me"), per-row remove, and an optimistic update that converges on the reloaded artefact.
 */
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
        <DetailSection
            icon={<IconPeople />}
            title="Suggested reviewers"
            collapsible
            afterTitle={
                <Tooltip title="PostHog uses these suggestions to route the report. Add reviewers on the pull request to request a GitHub review.">
                    <span className="-m-1 flex cursor-help items-center p-1 text-base text-tertiary">
                        <IconInfo />
                    </span>
                </Tooltip>
            }
            rightSlot={
                <div className="flex items-center gap-2">
                    {isUpdatingReviewers && <Spinner className="size-3" />}
                    <LemonDropdown
                        visible={addOpen}
                        onClickOutside={() => setAddOpen(false)}
                        closeOnClickInside={false}
                        placement="bottom-end"
                        overlay={<ReviewerSearchList report={report} surface="detail_pane" />}
                    >
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={<IconPlus />}
                            onClick={() => setAddOpen((open) => !open)}
                        >
                            Add
                        </LemonButton>
                    </LemonDropdown>
                </div>
            }
        >
            {baseReviewers.length === 0 ? (
                <span className="text-xs text-tertiary">No suggested reviewers. Select Add to suggest one.</span>
            ) : (
                <SuggestedReviewersList
                    reviewers={baseReviewers}
                    disabled={isUpdatingReviewers}
                    onRemove={removeReviewers}
                />
            )}
        </DetailSection>
    )
}
