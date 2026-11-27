import { Button } from '@posthog/quill'

import type { AEOBrandPromptApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { AiVisibilityCard } from './AiVisibilityCard'
import { AiVisibilityTable } from './AiVisibilityTable'
import { REPORT_TABLE_PAGE_SIZE } from './aiVisibilityTablePaging'
import { AiVisibilityTag } from './AiVisibilityTag'
import { ContentAutopilotEngineMarks } from './ContentAutopilotEngineMarks'
import { ContentAutopilotRateBar } from './ContentAutopilotRateBar'

/** The prompts whose answers name or cite a brand, the most such answers first. Each opens its prompt page. */
export const ContentAutopilotBrandPrompts = ({
    prompts,
    onOpenPrompt,
}: {
    prompts: AEOBrandPromptApi[]
    onOpenPrompt: (promptId: string) => void
}): JSX.Element => (
    <AiVisibilityCard title="Prompts that name the brand">
        <AiVisibilityTable<AEOBrandPromptApi>
            size="small"
            embedded
            data-attr="content-autopilot-brand-prompts"
            pagination={{ pageSize: REPORT_TABLE_PAGE_SIZE }}
            emptyState="No answer in this date range names this brand."
            dataSource={prompts}
            rowKey="id"
            columns={[
                {
                    title: 'Prompt',
                    key: 'text',
                    className: 'w-full max-w-0',
                    render: (_, prompt) => (
                        <Button
                            variant="link-foreground"
                            size="sm"
                            left
                            onClick={() => onOpenPrompt(prompt.id)}
                            className="max-w-full min-w-0 shrink"
                            title={prompt.text}
                            data-attr="content-autopilot-brand-prompt-open"
                        >
                            <span className="truncate">{prompt.text}</span>
                        </Button>
                    ),
                },
                {
                    title: 'Topic',
                    key: 'topic',
                    className: 'hidden @lg/ai-visibility-table:table-cell',
                    render: (_, prompt) =>
                        prompt.topic ? (
                            <AiVisibilityTag className="whitespace-nowrap">{prompt.topic}</AiVisibilityTag>
                        ) : (
                            <AiVisibilityTag type="muted" className="whitespace-nowrap">
                                No topic
                            </AiVisibilityTag>
                        ),
                },
                {
                    title: 'Engines',
                    key: 'engines',
                    className: 'hidden @md/ai-visibility-table:table-cell',
                    tooltip: 'Engines whose answers to this prompt name or cite the brand.',
                    render: (_, prompt) => <ContentAutopilotEngineMarks engines={prompt.engines} />,
                },
                {
                    title: 'Mention rate',
                    key: 'mention_rate',
                    align: 'right',
                    tooltip: 'Share of the answers to this prompt that name the brand or link to its site.',
                    sorter: (a, b) => a.mention_rate - b.mention_rate,
                    render: (_, prompt) => <ContentAutopilotRateBar rate={prompt.mention_rate} />,
                },
            ]}
        />
    </AiVisibilityCard>
)
