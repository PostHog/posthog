import { LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { AEOPromptCitationApi } from 'products/web_analytics/frontend/generated/api.schemas'

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
    <LemonTable<AEOPromptCitationApi>
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
                    <ContentAutopilotAnswerText text={citation.answer_text ?? ''} mentions={null} />
                </div>
            ),
        }}
        columns={[
            {
                title: 'Prompt',
                key: 'prompt_text',
                render: (_, citation) => (
                    <span className="flex flex-col gap-0.5 min-w-0 max-w-120">
                        <Link
                            onClick={() => onOpenPrompt(citation.prompt_id)}
                            className="text-left"
                            data-attr="content-autopilot-citations-prompt"
                        >
                            {citation.prompt_text}
                        </Link>
                        {citation.prompt_topic ? (
                            <span className="text-xs text-muted">{citation.prompt_topic}</span>
                        ) : null}
                    </span>
                ),
            },
            {
                title: 'Engine',
                key: 'engine',
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
                            <LemonTag type="success" size="small">
                                Mentioned
                            </LemonTag>
                        ) : null}
                    </span>
                ),
            },
            {
                title: 'Answered',
                key: 'created_at',
                render: (_, citation) => <TZLabel time={citation.created_at} />,
            },
        ]}
    />
)
