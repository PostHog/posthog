import { useActions, useValues } from 'kea'

import { Button, Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle, Text } from '@posthog/quill'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type { AEOCompetitorCandidateApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { aiVisibilityCompetitorReviewLogic } from './aiVisibilityCompetitorReviewLogic'
import { AiVisibilityTable } from './AiVisibilityTable'

const PAGE_SIZE = 5
// A narrow card has no room for the counts next to both actions.
const COUNT_COLUMN_CLASS = 'hidden @lg/ai-visibility-table:table-cell'

/** The setup step after the first checks: confirm which of the brands the answers name are competitors. */
export const AiVisibilityCompetitorReview = (): JSX.Element | null => {
    const { reviewShown, candidates, updatingIds, decisions } = useValues(aiVisibilityCompetitorReviewLogic)
    const { reviewCandidate, finishReview } = useActions(aiVisibilityCompetitorReviewLogic)

    // The step is optional, so it takes no space until the project is known to need it.
    if (!reviewShown) {
        return null
    }

    return (
        <Card size="sm" className="min-w-0" data-attr="ai-visibility-competitor-review">
            <CardHeader>
                <CardTitle role="heading" aria-level={3}>
                    Confirm your competitors
                </CardTitle>
                <CardDescription>
                    {candidates.length > 0
                        ? 'Answers to your non-branded prompts named and cited these brands in the last 7 days. Confirm the ones you compete with, and Rankings compares you against them by name.'
                        : 'No more suggestions. You can label other brands in settings.'}
                </CardDescription>
            </CardHeader>
            {candidates.length > 0 ? (
                <CardContent>
                    <AiVisibilityTable<AEOCompetitorCandidateApi>
                        size="small"
                        dataSource={candidates}
                        rowKey="brand_id"
                        pagination={{ pageSize: PAGE_SIZE }}
                        columns={[
                            {
                                title: 'Brand',
                                key: 'name',
                                className: 'w-full max-w-0',
                                render: (_, candidate) => (
                                    <div className="flex min-w-0 flex-col">
                                        <span className="truncate font-semibold">{candidate.name}</span>
                                        <Text size="xs" variant="muted" render={<span className="m-0 truncate" />}>
                                            {candidate.domain}
                                        </Text>
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
                                width: 0,
                                render: (_, candidate) => {
                                    const saving = updatingIds.includes(candidate.brand_id)
                                    return (
                                        <div className="flex justify-end gap-2 whitespace-nowrap">
                                            <Button
                                                onClick={() => reviewCandidate(candidate.brand_id, 'rejected')}
                                                disabledReason={saving ? 'Saving…' : undefined}
                                                data-attr="ai-visibility-competitor-review-reject"
                                            >
                                                Ignore
                                            </Button>
                                            <Button
                                                variant="outline"
                                                onClick={() => reviewCandidate(candidate.brand_id, 'confirmed')}
                                                loading={saving}
                                                data-attr="ai-visibility-competitor-review-confirm"
                                            >
                                                Competitor
                                            </Button>
                                        </div>
                                    )
                                },
                            },
                        ]}
                    />
                </CardContent>
            ) : null}
            <CardFooter className="flex flex-wrap items-center justify-between gap-2">
                <Text
                    size="xs"
                    variant="muted"
                    render={<span className="m-0" />}
                    data-attr="ai-visibility-competitor-review-count"
                >
                    {pluralize(decisions.confirmed, 'competitor')} confirmed
                </Text>
                <Button
                    variant={decisions.confirmed > 0 ? 'primary' : 'outline'}
                    onClick={finishReview}
                    data-attr="ai-visibility-competitor-review-finish"
                >
                    {decisions.confirmed > 0 || candidates.length === 0 ? 'Done' : 'Skip for now'}
                </Button>
            </CardFooter>
        </Card>
    )
}
