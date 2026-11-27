import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import {
    Card,
    CardContent,
    CardDescription,
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

import type { AEOCompetitorCandidateApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { aiVisibilityCompetitorReviewLogic } from './aiVisibilityCompetitorReviewLogic'
import { AiVisibilityTable } from './AiVisibilityTable'

const PAGE_SIZE = 5
// A narrow card has no room for the counts next to the brand.
const COUNT_COLUMN_CLASS = 'hidden @lg/ai-visibility-table:table-cell'

/** On First results, the brands the answers named, to pick competitors from. Leaving the step saves the picks. */
export const AiVisibilityCompetitorReview = (): JSX.Element | null => {
    const { reviewShown, reviewFailed, visibleCandidates, search, selectedIds, confirming } = useValues(
        aiVisibilityCompetitorReviewLogic
    )
    const { toggleCandidate, setSearch, loadReview } = useActions(aiVisibilityCompetitorReviewLogic)

    if (reviewFailed) {
        // The suggestions stay saved as suggested, so leaving the step without them loses nothing.
        return (
            <AiVisibilityBanner type="error" action={{ children: 'Try again', onClick: loadReview }}>
                Your suggested competitors didn't load. You can also review them later in settings.
            </AiVisibilityBanner>
        )
    }

    // The step is optional, so it takes no space until the project is known to need it.
    if (!reviewShown) {
        return null
    }

    return (
        <Card size="sm" className="min-w-0" data-attr="ai-visibility-competitor-review">
            <CardHeader>
                <CardTitle role="heading" aria-level={3}>
                    Your competitors
                </CardTitle>
                <CardDescription>
                    Answers to your non-branded prompts named these brands. Select the ones you compete with, and
                    Rankings compares you against them by name. Your likely competitors are already selected. You can
                    change them later in settings.
                </CardDescription>
            </CardHeader>
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
        </Card>
    )
}
