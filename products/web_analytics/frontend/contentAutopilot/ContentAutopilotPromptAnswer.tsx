import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSegmentedButton, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { ContentAutopilotCheckResultTag } from './ContentAutopilotCheckResultTag'
import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'
import { checkPromptVersion, engineLabel } from './utils'

// Engine output is third-party text: only plain http(s) URLs become links.
const isWebUrl = (url: string): boolean => /^https?:\/\//i.test(url)

export const ContentAutopilotPromptAnswer = (): JSX.Element => {
    const { engines, activeEngine, shownCheck, selectedCheck, latestChecksLoading, latestChecksFailed, promptId } =
        useValues(contentAutopilotPromptDetailLogic)
    const { selectEngine, loadAeoPromptLatestChecks } = useActions(contentAutopilotPromptDetailLogic)

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
                <LemonSegmentedButton
                    size="small"
                    value={selectedCheck ? undefined : (activeEngine ?? undefined)}
                    onChange={selectEngine}
                    options={engines.map((engine) => ({ value: engine, label: engineLabel(engine) }))}
                    data-attr="content-autopilot-prompt-answer-engine"
                />
                {selectedCheck ? (
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={() => selectEngine(selectedCheck.engine)}
                        data-attr="content-autopilot-prompt-answer-show-latest"
                    >
                        Show latest answer
                    </LemonButton>
                ) : null}
            </div>

            {shownCheck ? (
                <div className="flex flex-col gap-3">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                        <ContentAutopilotCheckResultTag
                            cited={shownCheck.cited}
                            checkFailed={shownCheck.check_failed}
                        />
                        <span>
                            {selectedCheck ? 'Older answer' : 'Latest answer'} from {engineLabel(shownCheck.engine)},{' '}
                            <TZLabel time={shownCheck.created_at} />
                        </span>
                        <span>Version {checkPromptVersion(shownCheck)}</span>
                        <span className="truncate">Model: {shownCheck.model}</span>
                    </div>

                    {shownCheck.check_failed ? (
                        <p className="m-0 text-muted">
                            The engine didn't answer this time.
                            {shownCheck.error ? ` Error: ${shownCheck.error}` : ''}
                        </p>
                    ) : (
                        <div className="whitespace-pre-wrap break-words text-sm bg-surface-secondary rounded p-3 max-h-96 overflow-y-auto">
                            {shownCheck.answer_text || 'The engine returned an empty answer.'}
                        </div>
                    )}

                    <div className="flex flex-col gap-1">
                        <h5 className="m-0">Cited sources ({shownCheck.cited_urls.length})</h5>
                        {shownCheck.cited_urls.length ? (
                            <ol className="m-0 pl-5 flex flex-col gap-1 text-sm">
                                {shownCheck.cited_urls.map((url, index) => (
                                    <li key={`${index}-${url}`} className="break-all">
                                        {isWebUrl(url) ? (
                                            <Link to={url} target="_blank">
                                                {url}
                                            </Link>
                                        ) : (
                                            url
                                        )}
                                        {shownCheck.target_urls.includes(url) ? (
                                            <LemonTag type="success" size="small" className="ml-2">
                                                Your site
                                            </LemonTag>
                                        ) : null}
                                    </li>
                                ))}
                            </ol>
                        ) : (
                            <span className="text-muted text-sm">This answer cited no sources.</span>
                        )}
                    </div>

                    <div className="flex flex-col gap-1">
                        <h5 className="m-0">Searches the engine ran ({shownCheck.search_queries.length})</h5>
                        {shownCheck.search_queries.length ? (
                            <ul className="m-0 pl-5 flex flex-col gap-1 text-sm">
                                {shownCheck.search_queries.map((query, index) => (
                                    <li key={`${index}-${query}`} className="break-words">
                                        {query}
                                    </li>
                                ))}
                            </ul>
                        ) : (
                            <span className="text-muted text-sm">The engine didn't report any searches.</span>
                        )}
                    </div>
                </div>
            ) : latestChecksLoading ? (
                <LemonSkeleton className="h-40 w-full" />
            ) : latestChecksFailed ? (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () => promptId && loadAeoPromptLatestChecks({ promptId, engines }),
                    }}
                >
                    Couldn't load the latest answers. Try again, and if it keeps happening contact support.
                </LemonBanner>
            ) : (
                <span className="text-muted">No answers yet. The prompt runs in the next daily check.</span>
            )}
        </div>
    )
}
