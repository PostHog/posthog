import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import {
    Button,
    Card,
    CardContent,
    CardDescription,
    CardFooter,
    CardHeader,
    CardTitle,
    Checkbox,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    InputGroupText,
    Text,
} from '@posthog/quill'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type { AEOCompetitorCandidateApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { aiVisibilityCompetitorReviewLogic } from './aiVisibilityCompetitorReviewLogic'
import { AiVisibilityTable } from './AiVisibilityTable'

const PAGE_SIZE = 5
// A narrow card has no room for the counts next to the brand.
const COUNT_COLUMN_CLASS = 'hidden @lg/ai-visibility-table:table-cell'

/** The setup step after the first checks: confirm which of the brands the answers name are competitors. */
export const AiVisibilityCompetitorReview = (): JSX.Element | null => {
    const { reviewShown, candidates, visibleCandidates, search, decisions, selectedIds, confirming } = useValues(
        aiVisibilityCompetitorReviewLogic
    )
    const { finishReview, toggleCandidate, confirmSelected, setSearch } = useActions(aiVisibilityCompetitorReviewLogic)

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
                        ? 'Answers to your current non-branded prompts named these brands in the last 7 days. Select the ones you compete with, and Rankings compares you against them by name. Your likely competitors are already selected, and the rest are left as they are.'
                        : 'No more suggestions. You can label other brands in settings.'}
                </CardDescription>
            </CardHeader>
            {candidates.length > 0 ? (
                <CardContent className="flex flex-col gap-2">
                    <InputGroup size="sm" className="w-72 max-w-full">
                        <InputGroupAddon align="inline-start">
                            <InputGroupText>
                                <IconSearch />
                            </InputGroupText>
                        </InputGroupAddon>
                        <InputGroupInput
                            type="search"
                            aria-label="Find a brand"
                            placeholder="Find a brand"
                            value={search}
                            onChange={(event) => setSearch(event.target.value)}
                            data-attr="ai-visibility-competitor-review-search"
                        />
                    </InputGroup>
                    <AiVisibilityTable<AEOCompetitorCandidateApi>
                        size="small"
                        dataSource={visibleCandidates}
                        emptyState={`No brand matches "${search}".`}
                        rowKey="brand_id"
                        pagination={{ pageSize: PAGE_SIZE }}
                        columns={[
                            {
                                key: 'select',
                                width: 0,
                                render: (_, candidate) => (
                                    <Checkbox
                                        checked={selectedIds.includes(candidate.brand_id)}
                                        onCheckedChange={(checked) => toggleCandidate(candidate.brand_id, checked)}
                                        disabledReason={confirming ? 'Saving…' : undefined}
                                        aria-label={`${candidate.name} is a competitor`}
                                        data-attr="ai-visibility-competitor-review-select"
                                    />
                                ),
                            },
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
                    {decisions.confirmed > 0 ? `${pluralize(decisions.confirmed, 'competitor')} confirmed` : ''}
                </Text>
                <div className="flex flex-wrap gap-2">
                    <Button
                        variant="outline"
                        onClick={finishReview}
                        disabledReason={confirming ? 'Saving…' : undefined}
                        data-attr="ai-visibility-competitor-review-finish"
                    >
                        {decisions.confirmed > 0 || candidates.length === 0 ? 'Done' : 'Skip for now'}
                    </Button>
                    {candidates.length > 0 ? (
                        <Button
                            variant="primary"
                            onClick={confirmSelected}
                            loading={confirming}
                            disabledReason={selectedIds.length === 0 ? 'Select the brands you compete with' : undefined}
                            data-attr="ai-visibility-competitor-review-confirm-selected"
                        >
                            {selectedIds.length > 0
                                ? `Confirm ${pluralize(selectedIds.length, 'competitor')}`
                                : 'Confirm competitors'}
                        </Button>
                    ) : null}
                </div>
            </CardFooter>
        </Card>
    )
}
