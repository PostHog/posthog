import { Button, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import type { AEOPromptCitationApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { AiVisibilityTable } from './AiVisibilityTable'
import { AiVisibilityTag } from './AiVisibilityTag'
import { ContentAutopilotAnswerText } from './ContentAutopilotAnswerText'
import { ContentAutopilotCheckResult } from './ContentAutopilotCheckResult'
import { ContentAutopilotEngineLabel } from './ContentAutopilotEngineLabel'

/** One row per answer behind a cited page, cited site or search. Expanding a row shows the answer. */
export const ContentAutopilotCitationsTable = ({
    citations,
    loading,
    onOpenPrompt,
}: {
    citations: AEOPromptCitationApi[]
    loading: boolean
    onOpenPrompt: (promptId: string) => void
}): JSX.Element => (
    <AiVisibilityTable<AEOPromptCitationApi>
        size="small"
        dataSource={citations}
        loading={loading}
        loadingSkeletonRows={4}
        rowKey="id"
        emptyState="No answers in this window. Older answers are left out."
        expandable={{
            noIndent: true,
            rowExpandable: (citation) => citation.answer_text !== null,
            expandedRowRender: (citation) => (
                <div className="p-2">
                    <ContentAutopilotAnswerText text={citation.answer_text ?? ''} mentions={null} sentences={[]} />
                </div>
            ),
        }}
        columns={[
            {
                title: 'Prompt',
                key: 'prompt_text',
                className: 'w-full max-w-0',
                render: (_, citation) => (
                    <span className="flex min-w-0 flex-col items-start gap-0.5">
                        <Button
                            variant="link-foreground"
                            size="sm"
                            left
                            onClick={() => onOpenPrompt(citation.prompt_id)}
                            // Not the cell's direct child, so quill's cell rule doesn't pull it into line.
                            className="-ms-2 max-w-full min-w-0 shrink"
                            title={citation.prompt_text}
                            data-attr="content-autopilot-citations-prompt"
                        >
                            <span className="truncate">{citation.prompt_text}</span>
                        </Button>
                        {citation.prompt_topic ? (
                            <Text size="xs" variant="muted" render={<span className="m-0 max-w-full truncate" />}>
                                {citation.prompt_topic}
                            </Text>
                        ) : null}
                    </span>
                ),
            },
            {
                title: 'Engine',
                key: 'engine',
                className: 'hidden @lg/ai-visibility-table:table-cell',
                render: (_, citation) => <ContentAutopilotEngineLabel engine={citation.engine} />,
            },
            {
                title: 'Your brand',
                key: 'cited',
                render: (_, citation) => (
                    <span className="inline-flex items-center gap-2 whitespace-nowrap">
                        <ContentAutopilotCheckResult
                            cited={citation.cited}
                            checkFailed={citation.check_failed}
                            position={citation.target_best_position}
                        />
                        {citation.mentioned && !citation.cited ? (
                            <AiVisibilityTag type="success">Mentioned</AiVisibilityTag>
                        ) : null}
                    </span>
                ),
            },
            {
                title: 'Answered',
                key: 'created_at',
                className: 'hidden @md/ai-visibility-table:table-cell whitespace-nowrap',
                render: (_, citation) => <TZLabel time={citation.created_at} />,
            },
        ]}
    />
)
