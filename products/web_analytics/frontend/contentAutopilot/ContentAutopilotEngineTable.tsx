import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { AEOPromptEngineStatsApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { AiVisibilityTable } from './AiVisibilityTable'
import { ContentAutopilotEngineLabel } from './ContentAutopilotEngineLabel'
import { ContentAutopilotRateBar } from './ContentAutopilotRateBar'
import { POSITION_DESCRIPTION, positionLabel } from './promptReport'

// The fields the prompt set overview and a single prompt's stats both carry per engine.
type EngineRow = Pick<
    AEOPromptEngineStatsApi,
    'engine' | 'mention_rate' | 'citation_rate' | 'avg_position' | 'checks' | 'failed'
>

/** Mention rate, citation rate and position side by side for each engine that answered in the window. */
export const ContentAutopilotEngineTable = ({ engines }: { engines: EngineRow[] }): JSX.Element => (
    <AiVisibilityTable<EngineRow>
        size="small"
        embedded
        dataSource={engines}
        rowKey="engine"
        emptyState="No engine answered in this window."
        columns={[
            {
                title: 'Engine',
                key: 'engine',
                className: 'w-full max-w-0',
                render: (_, { engine }) => <ContentAutopilotEngineLabel engine={engine} />,
            },
            {
                title: 'Visibility',
                key: 'mention_rate',
                align: 'right',
                render: (_, { mention_rate }) => <ContentAutopilotRateBar rate={mention_rate} />,
            },
            {
                title: 'Cited',
                key: 'citation_rate',
                align: 'right',
                render: (_, { citation_rate }) => <ContentAutopilotRateBar rate={citation_rate} />,
            },
            {
                title: 'Position',
                key: 'avg_position',
                align: 'right',
                tooltip: POSITION_DESCRIPTION,
                render: (_, { avg_position }) =>
                    avg_position === null ? (
                        <span className="text-muted-foreground">-</span>
                    ) : (
                        <span className="tabular-nums">{positionLabel(avg_position)}</span>
                    ),
            },
            {
                title: 'Answers',
                key: 'answers',
                align: 'right',
                className: 'hidden @md/ai-visibility-table:table-cell',
                render: (_, { checks, failed }) => (
                    <span className="tabular-nums text-muted-foreground">{humanFriendlyNumber(checks - failed)}</span>
                ),
            },
        ]}
    />
)
