import { LemonTable } from '@posthog/lemon-ui'

import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import type { AEOPromptEngineStatsApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { ContentAutopilotEngineLabel } from './ContentAutopilotEngineLabel'
import { POSITION_DESCRIPTION, positionLabel } from './promptReport'

const rateCell = (rate: number | null): JSX.Element =>
    rate === null ? <span className="text-muted">-</span> : <span className="tabular-nums">{percentage(rate, 0)}</span>

// The fields the prompt set overview and a single prompt's stats both carry per engine.
type EngineRow = Pick<
    AEOPromptEngineStatsApi,
    'engine' | 'mention_rate' | 'citation_rate' | 'avg_position' | 'checks' | 'failed'
>

/** Mention rate, citation rate and position side by side for each engine that answered in the window. */
export const ContentAutopilotEngineTable = ({ engines }: { engines: EngineRow[] }): JSX.Element => (
    <LemonTable<EngineRow>
        size="small"
        embedded
        dataSource={engines}
        rowKey="engine"
        columns={[
            {
                title: 'Engine',
                key: 'engine',
                render: (_, { engine }) => <ContentAutopilotEngineLabel engine={engine} />,
            },
            {
                title: 'Mentioned',
                key: 'mention_rate',
                align: 'right',
                render: (_, { mention_rate }) => rateCell(mention_rate),
            },
            {
                title: 'Cited',
                key: 'citation_rate',
                align: 'right',
                render: (_, { citation_rate }) => rateCell(citation_rate),
            },
            {
                title: 'Position',
                key: 'avg_position',
                align: 'right',
                tooltip: POSITION_DESCRIPTION,
                render: (_, { avg_position }) =>
                    avg_position === null ? (
                        <span className="text-muted">-</span>
                    ) : (
                        <span className="tabular-nums">{positionLabel(avg_position)}</span>
                    ),
            },
            {
                title: 'Answers',
                key: 'answers',
                align: 'right',
                render: (_, { checks, failed }) => (
                    <span className="tabular-nums text-secondary">{humanFriendlyNumber(checks - failed)}</span>
                ),
            },
        ]}
    />
)
