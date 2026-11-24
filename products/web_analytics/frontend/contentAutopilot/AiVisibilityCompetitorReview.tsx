import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard, LemonTable } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type { AEOCompetitorCandidateApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { aiVisibilityCompetitorReviewLogic } from './aiVisibilityCompetitorReviewLogic'

const PAGE_SIZE = 5
// A narrow card has no room for the counts next to both actions.
const COUNT_COLUMN_CLASS = 'hidden @lg/competitor-review:table-cell'

/** The setup step after the first checks: confirm which of the brands the answers name are competitors. */
export const AiVisibilityCompetitorReview = (): JSX.Element | null => {
    const { reviewShown, candidates, updatingIds, decisions } = useValues(aiVisibilityCompetitorReviewLogic)
    const { reviewCandidate, finishReview } = useActions(aiVisibilityCompetitorReviewLogic)

    // The step is optional, so it takes no space until the project is known to need it.
    if (!reviewShown) {
        return null
    }

    return (
        <LemonCard
            hoverEffect={false}
            className="@container/competitor-review p-4"
            data-attr="ai-visibility-competitor-review"
        >
            <h3 className="m-0">Confirm your competitors</h3>
            <p className="m-0 mt-1 mb-4 text-secondary">
                {candidates.length > 0
                    ? 'Answers to your non-branded prompts named and cited these brands in the last 7 days. Confirm the ones you compete with, and Rankings compares you against them by name.'
                    : 'No more suggestions. You can label other brands in settings.'}
            </p>
            {candidates.length > 0 ? (
                <div className="overflow-x-auto">
                    <LemonTable<AEOCompetitorCandidateApi>
                        size="small"
                        dataSource={candidates}
                        rowKey="brand_id"
                        pagination={{ pageSize: PAGE_SIZE }}
                        columns={[
                            {
                                title: 'Brand',
                                key: 'name',
                                render: (_, candidate) => (
                                    <div className="flex flex-col">
                                        <span className="font-semibold">{candidate.name}</span>
                                        <span className="text-xs text-muted">{candidate.domain}</span>
                                    </div>
                                ),
                            },
                            {
                                title: 'Named in',
                                key: 'answers_naming',
                                className: COUNT_COLUMN_CLASS,
                                align: 'right',
                                tooltip: 'Answers to non-branded prompts that name the brand.',
                                render: (_, candidate) => humanFriendlyNumber(candidate.answers_naming),
                            },
                            {
                                title: 'Cited in',
                                key: 'answers_citing',
                                className: COUNT_COLUMN_CLASS,
                                align: 'right',
                                tooltip: "Answers to non-branded prompts that cite a page on the brand's site.",
                                render: (_, candidate) => humanFriendlyNumber(candidate.answers_citing),
                            },
                            {
                                key: 'actions',
                                render: (_, candidate) => {
                                    const saving = updatingIds.includes(candidate.brand_id)
                                    return (
                                        <div className="flex justify-end gap-2 whitespace-nowrap">
                                            <LemonButton
                                                size="small"
                                                onClick={() => reviewCandidate(candidate.brand_id, 'rejected')}
                                                disabledReason={saving ? 'Saving…' : undefined}
                                                data-attr="ai-visibility-competitor-review-reject"
                                            >
                                                Ignore
                                            </LemonButton>
                                            <LemonButton
                                                type="secondary"
                                                size="small"
                                                onClick={() => reviewCandidate(candidate.brand_id, 'confirmed')}
                                                loading={saving}
                                                data-attr="ai-visibility-competitor-review-confirm"
                                            >
                                                Competitor
                                            </LemonButton>
                                        </div>
                                    )
                                },
                            },
                        ]}
                    />
                </div>
            ) : null}
            <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs text-secondary" data-attr="ai-visibility-competitor-review-count">
                    {pluralize(decisions.confirmed, 'competitor')} confirmed
                </span>
                <LemonButton
                    type={decisions.confirmed > 0 ? 'primary' : 'secondary'}
                    onClick={finishReview}
                    data-attr="ai-visibility-competitor-review-finish"
                >
                    {decisions.confirmed > 0 || candidates.length === 0 ? 'Done' : 'Skip for now'}
                </LemonButton>
            </div>
        </LemonCard>
    )
}
