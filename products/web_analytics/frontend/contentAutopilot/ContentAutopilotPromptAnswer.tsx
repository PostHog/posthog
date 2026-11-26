import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { Button, Heading, Skeleton, Text, ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { AiVisibilityTag } from './AiVisibilityTag'
import { ContentAutopilotAnswerMentionList } from './ContentAutopilotAnswerMentionList'
import { ContentAutopilotAnswerSentimentTag } from './ContentAutopilotAnswerSentimentTag'
import { ContentAutopilotAnswerText } from './ContentAutopilotAnswerText'
import { ContentAutopilotCheckResult } from './ContentAutopilotCheckResult'
import { ContentAutopilotCitationsLink } from './ContentAutopilotCitationsLink'
import { CITATIONS_MAX_DATE_FROM } from './contentAutopilotCitationsModalLogic'
import { ContentAutopilotEngineLabel } from './ContentAutopilotEngineLabel'
import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'
import { checkPromptVersion, engineLabel } from './utils'

// Engine output is third-party text: only plain http(s) URLs become links.
const isWebUrl = (url: string): boolean => /^https?:\/\//i.test(url)

export const ContentAutopilotPromptAnswer = (): JSX.Element => {
    const {
        engines,
        activeEngine,
        shownCheck,
        shownAnswerMentions,
        competitorBrands,
        competitorBrandsLoading,
        competitorBrandsFailed,
        selectedCheck,
        latestChecksLoading,
        latestChecksFailed,
        promptId,
    } = useValues(contentAutopilotPromptDetailLogic)
    const { selectEngine, loadAeoPromptLatestChecks, loadCompetitorBrands } = useActions(
        contentAutopilotPromptDetailLogic
    )

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
                <ToggleGroup
                    variant="outline"
                    spacing={1}
                    className="flex-wrap"
                    aria-label="Engine"
                    value={!selectedCheck && activeEngine ? [activeEngine] : []}
                    onValueChange={(next: string[]) => {
                        // Clicking the chosen engine again empties the group, which keeps the current engine.
                        if (next[0]) {
                            selectEngine(next[0])
                        }
                    }}
                    data-attr="content-autopilot-prompt-answer-engine"
                >
                    {engines.map((engine) => (
                        <ToggleGroupItem key={engine} value={engine}>
                            <ContentAutopilotEngineLabel engine={engine} />
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
                {selectedCheck ? (
                    <Button
                        variant="outline"
                        onClick={() => selectEngine(selectedCheck.engine)}
                        data-attr="content-autopilot-prompt-answer-show-latest"
                    >
                        Show latest answer
                    </Button>
                ) : null}
            </div>

            {shownCheck ? (
                <div className="flex flex-col gap-3">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        {shownCheck.mode === 'no_search' && !shownCheck.check_failed ? (
                            <AiVisibilityTag type="muted">No search</AiVisibilityTag>
                        ) : (
                            <ContentAutopilotCheckResult
                                cited={shownCheck.cited}
                                checkFailed={shownCheck.check_failed}
                                position={shownCheck.target_best_position}
                            />
                        )}
                        {shownCheck.check_failed ? null : (
                            <ContentAutopilotAnswerSentimentTag
                                sentiment={shownCheck.brand_sentiment ?? null}
                                score={shownCheck.brand_sentiment_score ?? null}
                                namesBrand={shownAnswerMentions?.mentions.some((m) => m.brand.isOwn) ?? false}
                            />
                        )}
                        <span>
                            {selectedCheck ? 'Older answer' : 'Latest answer'} from {engineLabel(shownCheck.engine)},{' '}
                            <TZLabel time={shownCheck.created_at} />
                        </span>
                        <span>Version {checkPromptVersion(shownCheck)}</span>
                        <span className="min-w-0 break-all">Model: {shownCheck.model}</span>
                    </div>

                    {shownCheck.check_failed ? (
                        <Text size="xs" variant="muted" className="m-0 break-words">
                            The engine didn't answer this time.
                            {shownCheck.error ? ` Error: ${shownCheck.error}` : ''}
                        </Text>
                    ) : (
                        <>
                            <div className="grid grid-cols-1 @3xl/prompt-report:grid-cols-3 gap-4">
                                <div className="min-w-0 @3xl/prompt-report:col-span-2">
                                    <ContentAutopilotAnswerText
                                        text={shownCheck.answer_text ?? ''}
                                        mentions={shownAnswerMentions}
                                        sentences={shownCheck.brand_sentiment_sentences}
                                    />
                                </div>
                                <ContentAutopilotAnswerMentionList
                                    mentions={shownAnswerMentions?.mentions ?? []}
                                    competitors={
                                        competitorBrands !== null
                                            ? 'ready'
                                            : competitorBrandsFailed && !competitorBrandsLoading
                                              ? 'failed'
                                              : 'loading'
                                    }
                                    onRetryCompetitors={() => loadCompetitorBrands()}
                                />
                            </div>

                            <div className="flex flex-col gap-1">
                                <Heading size="sm" render={<h5 className="m-0" />}>
                                    Cited sources ({shownCheck.cited_urls.length})
                                </Heading>
                                {shownCheck.cited_urls.length ? (
                                    <ol className="m-0 pl-5 flex flex-col gap-1 text-xs">
                                        {shownCheck.cited_urls.map((url, index) => (
                                            <li key={`${index}-${url}`} className="break-all">
                                                <ContentAutopilotCitationsLink
                                                    lookup={{
                                                        kind: 'url',
                                                        value: url,
                                                        dateFrom: CITATIONS_MAX_DATE_FROM,
                                                        dateTo: null,
                                                        branded: 'all',
                                                    }}
                                                    source="prompt-answer-sources"
                                                    className="break-all"
                                                >
                                                    {url}
                                                </ContentAutopilotCitationsLink>
                                                {isWebUrl(url) ? (
                                                    <Button
                                                        size="icon-xs"
                                                        nativeButton={false}
                                                        render={<LinkPrimitive to={url} target="_blank" />}
                                                        aria-label="Open the page"
                                                        tooltip="Open the page"
                                                        className="ml-1 inline-flex align-middle"
                                                        data-attr="content-autopilot-prompt-answer-source-open"
                                                    >
                                                        <IconExternal />
                                                    </Button>
                                                ) : null}
                                                {shownCheck.target_urls.includes(url) ? (
                                                    <AiVisibilityTag type="success" className="ml-2">
                                                        Your site
                                                    </AiVisibilityTag>
                                                ) : null}
                                            </li>
                                        ))}
                                    </ol>
                                ) : (
                                    <Text size="xs" variant="muted" className="m-0">
                                        This answer cited no sources.
                                    </Text>
                                )}
                            </div>

                            <div className="flex flex-col gap-1">
                                <Heading size="sm" render={<h5 className="m-0" />}>
                                    Searches the engine ran ({shownCheck.search_queries.length})
                                </Heading>
                                {shownCheck.search_queries.length ? (
                                    <ul className="m-0 pl-5 flex flex-col gap-1 text-xs">
                                        {shownCheck.search_queries.map((query, index) => (
                                            <li key={`${index}-${query}`} className="break-words">
                                                <ContentAutopilotCitationsLink
                                                    lookup={{
                                                        kind: 'search',
                                                        value: query,
                                                        dateFrom: CITATIONS_MAX_DATE_FROM,
                                                        dateTo: null,
                                                        branded: 'all',
                                                    }}
                                                    source="prompt-answer-searches"
                                                    className="break-words"
                                                >
                                                    {query}
                                                </ContentAutopilotCitationsLink>
                                            </li>
                                        ))}
                                    </ul>
                                ) : (
                                    <Text size="xs" variant="muted" className="m-0">
                                        The engine didn't report any searches.
                                    </Text>
                                )}
                            </div>
                        </>
                    )}
                </div>
            ) : latestChecksLoading ? (
                <Skeleton className="h-40 w-full" />
            ) : latestChecksFailed ? (
                <AiVisibilityBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () => promptId && loadAeoPromptLatestChecks({ promptId, engines }),
                    }}
                >
                    Couldn't load the latest answers. Try again, and if it keeps happening contact support.
                </AiVisibilityBanner>
            ) : (
                <Text size="xs" variant="muted" className="m-0">
                    No answers yet. The prompt runs in the next daily check.
                </Text>
            )}
        </div>
    )
}
