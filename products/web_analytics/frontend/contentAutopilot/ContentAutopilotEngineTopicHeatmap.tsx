import clsx from 'clsx'

import { LemonTable, LemonTableColumn, LemonTableColumns, Link, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'

import { ContentAutopilotEngineLabel } from './ContentAutopilotEngineLabel'
import type { EngineTopicCell, EngineTopicGrid, EngineTopicRow } from './promptsOverview'
import { sameTopic } from './utils'

// One fill per heat step, lowest rate first. Each is mixed from one token over the card, so the text on it keeps
// the theme's text color in light and dark mode. The classes are spelled out because Tailwind only emits the
// class names it finds in the source.
const HEAT_FILLS = [
    'bg-[color-mix(in_oklab,var(--success)_7%,transparent)]',
    'bg-[color-mix(in_oklab,var(--success)_17%,transparent)]',
    'bg-[color-mix(in_oklab,var(--success)_28%,transparent)]',
    'bg-[color-mix(in_oklab,var(--success)_40%,transparent)]',
    'bg-[color-mix(in_oklab,var(--success)_52%,transparent)]',
]

const HeatCell = ({ cell }: { cell: EngineTopicCell }): JSX.Element =>
    cell.rate === null || cell.heat === null ? (
        <Tooltip title="No answers">
            <span className="block px-2 py-1 text-center text-muted" aria-label="No answers">
                -
            </span>
        </Tooltip>
    ) : (
        <Tooltip title={`Visible in ${humanFriendlyNumber(cell.mentioned)} of ${pluralize(cell.answers, 'answer')}`}>
            <span
                className={clsx(
                    'block rounded px-2 py-1 text-center whitespace-nowrap tabular-nums',
                    HEAT_FILLS[cell.heat]
                )}
            >
                <span className="font-semibold">{percentage(cell.rate, 0)}</span>{' '}
                <span className="text-xs">of {humanFriendlyNumber(cell.answers)}</span>
            </span>
        </Tooltip>
    )

/** Mention rate per topic and engine as a grid, so an engine that skips one topic stands out. Picking a row
 *  filters the page to that topic, and picking it again clears the filter. */
export const ContentAutopilotEngineTopicHeatmap = ({
    grid,
    selectedTopic,
    onSelectTopic,
}: {
    grid: EngineTopicGrid
    selectedTopic: string | null
    onSelectTopic: (topic: string) => void
}): JSX.Element => {
    const columns: LemonTableColumns<EngineTopicRow> = [
        {
            title: 'Topic',
            key: 'topic',
            render: (_, row) => (
                <Link
                    subtle
                    onClick={(event) => {
                        // The row handler below would otherwise select the topic a second time.
                        event.stopPropagation()
                        onSelectTopic(row.topic)
                    }}
                    className={row.topic ? 'font-semibold' : 'font-semibold text-muted'}
                    data-attr="content-autopilot-prompts-overview-heatmap-topic"
                >
                    {row.topic || 'No topic'}
                </Link>
            ),
        },
        ...grid.engines.map(
            (engine, index): LemonTableColumn<EngineTopicRow, keyof EngineTopicRow | undefined> => ({
                title: <ContentAutopilotEngineLabel engine={engine} />,
                key: engine,
                align: 'center',
                render: (_, row) => <HeatCell cell={row.cells[index]} />,
            })
        ),
    ]
    return (
        <PagePerformanceCard className="min-w-0">
            <PagePerformanceCardHeader title="Visibility by engine and topic" />
            <div className="overflow-x-auto" data-attr="content-autopilot-prompts-overview-heatmap">
                <LemonTable
                    size="small"
                    embedded
                    dataSource={grid.rows}
                    rowKey="topic"
                    columns={columns}
                    rowStatus={(row) => (sameTopic(row.topic, selectedTopic) ? 'highlighted' : null)}
                    rowClassName="cursor-pointer"
                    onRow={(row) => ({ onClick: () => onSelectTopic(row.topic) })}
                    emptyState="No topics yet"
                />
            </div>
        </PagePerformanceCard>
    )
}
