import type { LemonTableColumn } from '@posthog/lemon-ui'
import { Button, Text } from '@posthog/quill'

import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import type { AEOPromptSetTopicCountsApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { AiVisibilityTable } from './AiVisibilityTable'
import { sameTopic } from './utils'

type TopicRow = AEOPromptSetTopicCountsApi
type TopicColumn = LemonTableColumn<TopicRow, keyof TopicRow | undefined>

const byRate = (key: 'mention_rate' | 'citation_rate') => (a: TopicRow, b: TopicRow) => (a[key] ?? -1) - (b[key] ?? -1)

const RateCell = ({ rate, answers }: { rate: number | null; answers: number }): JSX.Element =>
    rate === null ? (
        <Text size="xs" variant="muted" render={<span />}>
            No answers
        </Text>
    ) : (
        <span className="tabular-nums">
            {percentage(rate, 0)}{' '}
            <Text size="xs" variant="muted" render={<span />}>
                of {humanFriendlyNumber(answers)}
            </Text>
        </span>
    )

/** One row per topic. Picking a row filters the page to that topic, and picking it again clears the filter. */
export const ContentAutopilotPromptsTopicTable = ({
    rows,
    selectedTopic,
    onSelect,
}: {
    rows: TopicRow[]
    selectedTopic: string | null
    onSelect: (topic: string) => void
}): JSX.Element => {
    const columns: TopicColumn[] = [
        {
            title: 'Topic',
            key: 'topic',
            sorter: (a, b) => a.topic.localeCompare(b.topic),
            render: (_, row) => (
                <Button
                    variant={row.topic ? 'link-foreground' : 'link-muted'}
                    size="sm"
                    left
                    onClick={(event) => {
                        // The row handler below would otherwise select the topic a second time.
                        event.stopPropagation()
                        onSelect(row.topic)
                    }}
                    className="max-w-full shrink font-semibold"
                    data-attr="content-autopilot-prompts-overview-topic"
                >
                    <span className="truncate">{row.topic || 'No topic'}</span>
                </Button>
            ),
        },
        {
            title: 'Prompts',
            key: 'active_prompts',
            align: 'right',
            sorter: (a, b) => a.active_prompts - b.active_prompts,
            render: (_, row) => <span className="tabular-nums">{row.active_prompts}</span>,
        },
        {
            title: 'Visibility',
            key: 'mention_rate',
            align: 'right',
            sorter: byRate('mention_rate'),
            render: (_, row) => <RateCell rate={row.mention_rate} answers={row.checks - row.failed} />,
        },
        {
            title: 'Cited',
            key: 'citation_rate',
            align: 'right',
            sorter: byRate('citation_rate'),
            render: (_, row) => <RateCell rate={row.citation_rate} answers={row.checks - row.failed} />,
        },
    ]
    return (
        <AiVisibilityTable
            size="small"
            embedded
            dataSource={rows}
            rowKey="topic"
            columns={columns}
            defaultSorting={{ columnKey: 'mention_rate', order: -1 }}
            rowStatus={(row) => (sameTopic(row.topic, selectedTopic) ? 'highlighted' : null)}
            rowClassName="cursor-pointer"
            onRow={(row) => ({ onClick: () => onSelect(row.topic) })}
            emptyState="No topics yet"
        />
    )
}
