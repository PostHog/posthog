import { Button } from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import type { AEOPromptMoverApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { AiVisibilityTable } from './AiVisibilityTable'
import { ContentAutopilotKpiDelta } from './ContentAutopilotKpiDelta'
import { ContentAutopilotRateBar } from './ContentAutopilotRateBar'
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
    <AiVisibilityTable<AEOPromptMoverApi>
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
                    <Button
                        variant="link-foreground"
                        size="sm"
                        onClick={() => onOpenPrompt(mover)}
                        // A button sizes to its text, so it needs the cell's width to truncate.
                        className="w-full max-w-full justify-start font-semibold"
                        title={mover.prompt}
                        data-attr="content-autopilot-movers-prompt"
                    >
                        <span className="truncate">{mover.prompt}</span>
                    </Button>
                ),
            },
            {
                title: 'Now',
                key: 'mention_rate',
                align: 'right',
                tooltip: 'Visibility in this date range.',
                render: (_, { mention_rate, answers }) => (
                    <ContentAutopilotRateBar rate={mention_rate} tooltip={`Out of ${pluralize(answers, 'answer')}`} />
                ),
            },
            {
                title: 'Before',
                key: 'previous_mention_rate',
                align: 'right',
                tooltip: `Visibility in the ${days} days before.`,
                render: (_, { previous_mention_rate, previous_answers }) => (
                    <ContentAutopilotRateBar
                        rate={previous_mention_rate}
                        tooltip={`Out of ${pluralize(previous_answers, 'answer')}`}
                    />
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
