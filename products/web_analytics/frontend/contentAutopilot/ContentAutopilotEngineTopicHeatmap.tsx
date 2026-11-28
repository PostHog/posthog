import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import type { LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { AiVisibilityCard } from './AiVisibilityCard'
import { AiVisibilityTable } from './AiVisibilityTable'
import { ContentAutopilotEngineLabel } from './ContentAutopilotEngineLabel'
import type { EngineTopicCell, EngineTopicGrid, EngineTopicRow } from './promptsOverview'
import { formatShare } from './shares'
import { sameTopic } from './utils'

// How much of the strong success color each heat step mixes over the card, lowest rate first, so the text on it keeps
// the theme's text color in light and dark mode. A mix in a style, because quill's scoped colors take no opacity modifier.
const HEAT_SHARES = [5, 15, 25, 35, 50]

const HeatCell = ({ cell }: { cell: EngineTopicCell }): JSX.Element =>
    cell.rate === null || cell.heat === null ? (
        <Tooltip>
            <TooltipTrigger
                render={<span className="block px-2 py-1 text-center text-muted-foreground" aria-label="No answers" />}
            >
                -
            </TooltipTrigger>
            <TooltipContent>No answers</TooltipContent>
        </Tooltip>
    ) : (
        <Tooltip>
            <TooltipTrigger
                render={
                    <span
                        className="block rounded-sm px-2 py-1 text-center whitespace-nowrap tabular-nums"
                        style={{
                            backgroundColor: `color-mix(in oklab, var(--success-foreground) ${HEAT_SHARES[cell.heat]}%, transparent)`,
                        }}
                    />
                }
            >
                <span className="font-semibold">{formatShare(cell.rate)}</span>
            </TooltipTrigger>
            <TooltipContent>
                Visible in {humanFriendlyNumber(cell.mentioned)} of {pluralize(cell.answers, 'answer')}
            </TooltipContent>
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
                <Button
                    variant={row.topic ? 'link-foreground' : 'link-muted'}
                    size="sm"
                    onClick={(event) => {
                        // The row handler below would otherwise select the topic a second time.
                        event.stopPropagation()
                        onSelectTopic(row.topic)
                    }}
                    className="font-semibold"
                    data-attr="content-autopilot-prompts-overview-heatmap-topic"
                >
                    {row.topic || 'No topic'}
                </Button>
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
        <AiVisibilityCard title="Visibility by engine and topic">
            <div className="overflow-x-auto" data-attr="content-autopilot-prompts-overview-heatmap">
                <AiVisibilityTable
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
        </AiVisibilityCard>
    )
}
