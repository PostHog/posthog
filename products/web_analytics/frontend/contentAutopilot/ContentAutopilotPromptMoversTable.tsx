import { LemonTable, Link } from '@posthog/lemon-ui'

import { percentage } from 'lib/utils/numbers'

import type { AEOPromptMoverApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { ContentAutopilotKpiDelta } from './ContentAutopilotKpiDelta'
import { moverDelta } from './movers'

/** The prompts that moved, gains first. A prompt opens its page. */
export const ContentAutopilotPromptMoversTable = ({
    rows,
    days,
    onOpenPrompt,
}: {
    rows: AEOPromptMoverApi[]
    days: number
    onOpenPrompt: (prompt: AEOPromptMoverApi) => void
}): JSX.Element => (
    <LemonTable<AEOPromptMoverApi>
        size="small"
        embedded
        dataSource={rows}
        rowKey="prompt_id"
        columns={[
            {
                title: 'Prompt',
                key: 'prompt',
                // The cell takes the width the numbers leave, and the text truncates to it.
                className: 'w-full max-w-0',
                render: (_, mover) => (
                    <span className="block truncate font-semibold">
                        <Link
                            onClick={() => onOpenPrompt(mover)}
                            // A button sizes to its text, so it needs the cell's width to truncate.
                            className="block w-full truncate"
                            title={mover.prompt}
                            data-attr="content-autopilot-movers-prompt"
                        >
                            {mover.prompt}
                        </Link>
                    </span>
                ),
            },
            {
                title: 'Now',
                key: 'mention_rate',
                align: 'right',
                tooltip: 'Visibility in this date range.',
                render: (_, { mention_rate, answers }) => (
                    <span className="tabular-nums whitespace-nowrap">
                        {percentage(mention_rate, 0)} <span className="text-secondary">of {answers}</span>
                    </span>
                ),
            },
            {
                title: 'Before',
                key: 'previous_mention_rate',
                align: 'right',
                tooltip: `Visibility in the ${days} days before.`,
                render: (_, { previous_mention_rate, previous_answers }) => (
                    <span className="tabular-nums whitespace-nowrap">
                        {percentage(previous_mention_rate, 0)}{' '}
                        <span className="text-secondary">of {previous_answers}</span>
                    </span>
                ),
            },
            {
                title: 'Change',
                key: 'change',
                align: 'right',
                render: (_, { change }) => <ContentAutopilotKpiDelta delta={moverDelta(change, days)} />,
            },
        ]}
    />
)
