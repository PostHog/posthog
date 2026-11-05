import { LemonTable, LemonTableColumn, Link } from '@posthog/lemon-ui'

import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type { AEOPromptSetTopicCountsApi } from 'products/web_analytics/frontend/generated/api.schemas'

type TopicRow = AEOPromptSetTopicCountsApi
type TopicColumn = LemonTableColumn<TopicRow, keyof TopicRow | undefined>

const byRate = (key: 'mention_rate' | 'citation_rate') => (a: TopicRow, b: TopicRow) => (a[key] ?? -1) - (b[key] ?? -1)

const RateCell = ({ rate, answers }: { rate: number | null; answers: number }): JSX.Element =>
    rate === null ? (
        <span className="text-muted">No answers</span>
    ) : (
        <span className="tabular-nums">
            {percentage(rate, 0)} <span className="text-muted">of {answers}</span>
        </span>
    )

/** One row per topic. Picking a row filters the prompt list below to that topic. */
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
                <Link
                    subtle
                    onClick={(event) => {
                        // The row handler below would otherwise select the topic a second time.
                        event.stopPropagation()
                        onSelect(row.topic)
                    }}
                    className={row.topic ? 'font-semibold' : 'font-semibold text-muted'}
                    data-attr="content-autopilot-prompts-overview-topic"
                >
                    {row.topic || 'No topic'}
                </Link>
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
            title: 'Mentioned',
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
        <LemonTable
            size="small"
            embedded
            dataSource={rows}
            rowKey="topic"
            columns={columns}
            defaultSorting={{ columnKey: 'mention_rate', order: -1 }}
            rowStatus={(row) => (row.topic === selectedTopic ? 'highlighted' : null)}
            rowClassName="cursor-pointer"
            onRow={(row) => ({ onClick: () => onSelect(row.topic) })}
            emptyState="No topics yet"
            footer={
                <span className="px-3 py-2 text-xs text-muted">
                    {pluralize(rows.length, 'topic')}. Pick one to filter the prompts below.
                </span>
            }
        />
    )
}
