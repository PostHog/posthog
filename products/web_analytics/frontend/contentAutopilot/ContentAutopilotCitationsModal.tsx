import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'

import type { AEOPromptCitationApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { pageReportPath } from '../pageReports/pageReportsUtils'
import { ContentAutopilotAnswerText } from './ContentAutopilotAnswerText'
import { ContentAutopilotCheckResult } from './ContentAutopilotCheckResult'
import { type CitationsLookup, contentAutopilotCitationsModalLogic } from './contentAutopilotCitationsModalLogic'
import { ContentAutopilotEngineLabel } from './ContentAutopilotEngineLabel'
import { segmentPrompts } from './utils'

// Engine output is third-party text: only plain http(s) URLs become links.
const isWebUrl = (url: string): boolean => /^https?:\/\//i.test(url)

const modalTitle = ({ kind, value }: CitationsLookup): string =>
    kind === 'domain'
        ? `Answers that cite ${value}`
        : kind === 'url'
          ? 'Answers that cite this page'
          : `Answers that searched for "${value}"`

/** The answers behind the cited page, cited site or engine search picked anywhere on the AI visibility page. */
export const ContentAutopilotCitationsModal = (): JSX.Element => {
    const { lookup, citations, citationsLoading, citationsFailed, hasMoreCitations, isOwnPage } = useValues(
        contentAutopilotCitationsModalLogic
    )
    const { closeCitations, loadCitations, loadMoreCitations, openCitationPrompt } = useActions(
        contentAutopilotCitationsModalLogic
    )
    const externalUrl =
        lookup?.kind === 'domain' ? `https://${lookup.value}` : lookup?.kind === 'url' ? lookup.value : null

    return (
        <LemonModal
            isOpen={!!lookup}
            onClose={closeCitations}
            title={lookup ? modalTitle(lookup) : ''}
            description={
                lookup
                    ? `Answers to ${segmentPrompts(lookup.branded)} over the last ${lookup.days} days, newest first.`
                    : undefined
            }
            width={960}
        >
            {lookup ? (
                <div className="flex flex-col gap-3" data-attr="content-autopilot-citations-modal">
                    {externalUrl && isWebUrl(externalUrl) ? (
                        <div className="flex flex-wrap items-center gap-2">
                            {lookup.kind === 'url' ? (
                                <span className="min-w-0 break-all text-sm font-semibold">{lookup.value}</span>
                            ) : null}
                            <LemonButton
                                size="small"
                                type="secondary"
                                to={externalUrl}
                                targetBlank
                                data-attr="content-autopilot-citations-open-site"
                            >
                                {lookup.kind === 'url' ? 'Open page' : 'Open site'}
                            </LemonButton>
                            {isOwnPage ? (
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    to={pageReportPath(lookup.value)}
                                    tooltip="See this page's traffic, including visits from AI assistants"
                                    data-attr="content-autopilot-citations-page-report"
                                >
                                    Page report
                                </LemonButton>
                            ) : null}
                        </div>
                    ) : null}
                    {citationsFailed && !citations ? (
                        <LemonBanner
                            type="error"
                            action={{ children: 'Try again', onClick: loadCitations, loading: citationsLoading }}
                        >
                            Couldn't load the answers. Try again, and if it keeps happening contact support.
                        </LemonBanner>
                    ) : (
                        <>
                            {citations ? (
                                <span className="text-xs text-muted">{pluralize(citations.count, 'answer')}</span>
                            ) : null}
                            <LemonTable<AEOPromptCitationApi>
                                size="small"
                                dataSource={citations?.results ?? []}
                                loading={citationsLoading && !citations}
                                loadingSkeletonRows={4}
                                rowKey="id"
                                emptyState="No answers in this window. Older answers are left out."
                                expandable={{
                                    noIndent: true,
                                    rowExpandable: (citation) => citation.answer_text !== null,
                                    expandedRowRender: (citation) => (
                                        <div className="p-2">
                                            <ContentAutopilotAnswerText
                                                text={citation.answer_text ?? ''}
                                                mentions={null}
                                            />
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
                                                    onClick={() => openCitationPrompt(citation.prompt_id)}
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
                                        render: (_, citation) => (
                                            <ContentAutopilotEngineLabel engine={citation.engine} />
                                        ),
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
                            {hasMoreCitations ? (
                                <div className="flex justify-center">
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        onClick={loadMoreCitations}
                                        loading={citationsLoading}
                                        data-attr="content-autopilot-citations-load-more"
                                    >
                                        Show more answers
                                    </LemonButton>
                                </div>
                            ) : null}
                            {citationsFailed && citations ? (
                                <span className="text-xs text-danger">
                                    Couldn't load more answers. Try again, and if it keeps happening contact support.
                                </span>
                            ) : null}
                        </>
                    )}
                </div>
            ) : null}
        </LemonModal>
    )
}
