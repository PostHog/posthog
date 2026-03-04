import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonBanner, LemonButton, LemonTag, LemonTextArea, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { urls } from 'scenes/urls'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { Query } from '~/queries/Query/Query'
import { LLMPrompt, LLMPromptVersionSummary } from '~/types'

import { useTracesQueryContext } from '../LLMAnalyticsTracesScene'
import { PromptAnalyticsScope, isPrompt, llmPromptLogic } from './llmPromptLogic'

export function PromptViewDetails(): JSX.Element {
    const { prompt } = useValues(llmPromptLogic)

    if (!prompt || !isPrompt(prompt)) {
        return <></>
    }

    const promptText = prompt.prompt
    const variableMatches = promptText.match(/\{\{([^}]+)\}\}/g)
    const variables = variableMatches
        ? [...new Set(variableMatches.map((match: string) => match.slice(2, -2).trim()))]
        : []

    return (
        <div className="max-w-3xl space-y-5">
            <div className="flex flex-wrap items-center gap-2">
                <LemonTag type="highlight" size="small">
                    v{prompt.version}
                </LemonTag>
                {prompt.is_latest ? (
                    <LemonTag type="success" size="small">
                        Latest
                    </LemonTag>
                ) : (
                    <LemonTag type="muted" size="small">
                        Historical
                    </LemonTag>
                )}
                <span className="text-secondary text-sm">
                    Latest version is v{prompt.latest_version}. This prompt has {prompt.version_count} published version
                    {prompt.version_count === 1 ? '' : 's'}.
                </span>
            </div>

            <div>
                <label className="text-xs font-semibold uppercase text-secondary">Name</label>
                <p className="font-mono">{prompt.name}</p>
            </div>

            <div>
                <label className="text-xs font-semibold uppercase text-secondary">Prompt</label>
                <pre className="mt-1 rounded border bg-bg-light p-3 whitespace-pre-wrap">{prompt.prompt}</pre>
            </div>

            <div className="grid gap-3 text-sm text-secondary sm:grid-cols-2">
                <div>Published {dayjs(prompt.created_at).format('MMM D, YYYY h:mm A')}</div>
                <div>
                    First active version created {dayjs(prompt.first_version_created_at).format('MMM D, YYYY h:mm A')}
                </div>
            </div>

            {variables.length > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                    <span className="text-xs text-secondary">Variables:</span>
                    {variables.map((variable) => (
                        <LemonTag key={variable} type="highlight" size="small">
                            {variable}
                        </LemonTag>
                    ))}
                </div>
            )}
        </div>
    )
}

export function PromptRelatedTraces(): JSX.Element {
    const { prompt, relatedTracesQuery, viewAllTracesUrl, analyticsScope } = useValues(llmPromptLogic)
    const { setAnalyticsScope } = useActions(llmPromptLogic)
    const tracesQueryContext = useTracesQueryContext()

    if (!prompt || !isPrompt(prompt)) {
        return <></>
    }

    return (
        <div className="mt-8" data-attr="prompt-related-traces-section">
            <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                    <h3 className="text-lg font-semibold">Related traces</h3>
                    <p className="mt-1 text-sm text-secondary">
                        Send <code className="rounded bg-bg-light px-1">$ai_prompt_name</code>,{' '}
                        <code className="rounded bg-bg-light px-1">$ai_prompt_version</code>, and{' '}
                        <code className="rounded bg-bg-light px-1">$ai_prompt_version_id</code> with your LLM events for
                        version-specific attribution.
                    </p>
                </div>

                <div className="flex items-center gap-2">
                    <PromptAnalyticsScopeControls
                        analyticsScope={analyticsScope}
                        setAnalyticsScope={setAnalyticsScope}
                    />
                    <LemonButton
                        type="secondary"
                        to={viewAllTracesUrl}
                        size="small"
                        data-attr="prompt-view-all-traces-button"
                    >
                        View all traces
                    </LemonButton>
                </div>
            </div>

            {analyticsScope === PromptAnalyticsScope.Selected && (
                <LemonBanner type="info" className="mb-4">
                    Selected-version trace filtering uses <code>$ai_prompt_version_id</code>. If your events only send
                    the prompt name, switch to all current versions.
                </LemonBanner>
            )}

            {relatedTracesQuery && (
                <DataTable
                    query={relatedTracesQuery}
                    setQuery={() => {}}
                    context={tracesQueryContext}
                    uniqueKey="prompt-related-traces"
                    attachTo={llmPromptLogic}
                />
            )}
        </div>
    )
}

export function PromptUsage({ prompt }: { prompt: LLMPrompt }): JSX.Element {
    const { promptUsageLogQuery, promptUsageTrendQuery, analyticsScope } = useValues(llmPromptLogic)
    const { setAnalyticsScope } = useActions(llmPromptLogic)

    return (
        <div data-attr="prompt-usage-container">
            <LemonBanner type="info" className="mb-4">
                During the alpha and beta period, each prompt fetch is currently charged as a Product analytics event.
                See the{' '}
                <Link to="https://posthog.com/pricing" target="_blank">
                    pricing page
                </Link>
                .
            </LemonBanner>

            <div className="mb-4 flex items-center justify-between gap-2">
                <div>
                    <b>Trend</b>
                    <div className="text-secondary">
                        {analyticsScope === PromptAnalyticsScope.Selected
                            ? `Prompt fetches for "${prompt.name}" version ${prompt.version}`
                            : `Prompt fetches for all current versions of "${prompt.name}"`}
                    </div>
                </div>

                <PromptAnalyticsScopeControls analyticsScope={analyticsScope} setAnalyticsScope={setAnalyticsScope} />
            </div>
            <Query query={promptUsageTrendQuery} />

            <div className="mb-4 mt-6">
                <b>Log</b>
                <div className="text-secondary">
                    {analyticsScope === PromptAnalyticsScope.Selected
                        ? `Prompt fetch events for "${prompt.name}" version ${prompt.version}`
                        : `Prompt fetch events for all current versions of "${prompt.name}"`}
                </div>
            </div>
            <Query query={promptUsageLogQuery} />
        </div>
    )
}

export function PromptEditForm({
    isHistoricalVersion,
    selectedVersion,
}: {
    isHistoricalVersion: boolean
    selectedVersion: number | null
}): JSX.Element {
    const { promptVariables, isNewPrompt } = useValues(llmPromptLogic)

    return (
        <div className="max-w-3xl space-y-4">
            {isHistoricalVersion && selectedVersion ? (
                <LemonBanner type="info">
                    You are publishing a new latest version from historical version v{selectedVersion}. The original
                    version will remain unchanged.
                </LemonBanner>
            ) : null}

            <LemonField
                name="name"
                label="Name"
                help={
                    isNewPrompt
                        ? 'This name is used to fetch the prompt from your code. It must be unique and cannot be changed later. Only letters, numbers, hyphens (-), and underscores (_) are allowed.'
                        : 'This name is used to fetch the prompt from your code.'
                }
            >
                <LemonInput
                    name="name"
                    placeholder="my-prompt-name"
                    fullWidth
                    disabledReason={!isNewPrompt ? 'Prompt name cannot be changed after creation' : undefined}
                />
            </LemonField>

            <LemonField
                name="prompt"
                label="Prompt"
                help="Use {{variable_name}} to define variables that will be replaced when fetching the prompt from your backend."
            >
                <LemonTextArea
                    name="prompt"
                    placeholder="You are a helpful assistant for {{company_name}}. Help the user with their question about {{topic}}."
                    minRows={10}
                    className="font-mono"
                />
            </LemonField>

            {promptVariables.length > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                    <span className="text-xs text-secondary">Variables:</span>
                    {promptVariables.map((variable) => (
                        <LemonTag key={variable} type="highlight" size="small">
                            {variable}
                        </LemonTag>
                    ))}
                </div>
            )}
        </div>
    )
}

export function PromptVersionSidebar({
    promptName,
    prompt,
    versions,
    versionsLoading,
    canLoadMoreVersions,
    loadMoreVersions,
    searchParams,
}: {
    promptName: string
    prompt: LLMPrompt | null
    versions: LLMPromptVersionSummary[]
    versionsLoading: boolean
    canLoadMoreVersions: boolean
    loadMoreVersions: () => void
    searchParams: Record<string, any>
}): JSX.Element {
    return (
        <aside className="w-full shrink-0 xl:sticky xl:top-4 xl:w-80">
            <div className="rounded border bg-surface-primary p-4">
                <div className="mb-3 flex items-center justify-between">
                    <div>
                        <h3 className="font-semibold">Version history</h3>
                        <p className="text-sm text-secondary">
                            {versions.length} of {prompt?.version_count ?? versions.length} loaded
                        </p>
                    </div>
                </div>

                <div className="max-h-[28rem] space-y-2 overflow-y-auto pr-1">
                    {versions.map((versionPrompt) => {
                        const selected = prompt?.id === versionPrompt.id
                        const versionUrl = buildPromptUrl(
                            promptName,
                            searchParams,
                            versionPrompt.version,
                            versionPrompt.id
                        )

                        return (
                            <Link
                                key={versionPrompt.id}
                                to={versionUrl}
                                className={`block rounded border p-3 no-underline ${
                                    selected
                                        ? 'border-primary bg-primary-highlight'
                                        : 'border-primary/10 hover:bg-fill-secondary'
                                }`}
                                data-attr={`prompt-version-link-${versionPrompt.version}`}
                            >
                                <div className="mb-1 flex items-center gap-2">
                                    <span className="font-mono text-sm">v{versionPrompt.version}</span>
                                    {versionPrompt.is_latest ? (
                                        <LemonTag type="success" size="small">
                                            Latest
                                        </LemonTag>
                                    ) : null}
                                </div>
                                <div className="text-xs text-secondary">
                                    {dayjs(versionPrompt.created_at).format('MMM D, YYYY h:mm A')}
                                </div>
                                {versionPrompt.created_by?.email ? (
                                    <div className="mt-1 text-xs text-secondary">{versionPrompt.created_by.email}</div>
                                ) : null}
                            </Link>
                        )
                    })}
                </div>

                {canLoadMoreVersions ? (
                    <LemonButton
                        className="mt-3 w-full"
                        type="secondary"
                        onClick={loadMoreVersions}
                        loading={versionsLoading}
                        data-attr="prompt-load-more-versions"
                    >
                        Load more versions
                    </LemonButton>
                ) : null}
            </div>
        </aside>
    )
}

export function cleanPromptSearchParams(
    searchParams: Record<string, any>,
    version: number | null,
    versionId?: string | null
): Record<string, any> {
    const nextSearchParams = { ...searchParams }

    if (version) {
        nextSearchParams.version = version
    } else {
        delete nextSearchParams.version
    }

    if (versionId) {
        nextSearchParams.version_id = versionId
    } else {
        delete nextSearchParams.version_id
    }

    delete nextSearchParams.edit
    return nextSearchParams
}

export function buildPromptUrl(
    promptName: string,
    searchParams: Record<string, any>,
    version: number | null,
    versionId?: string | null
): string {
    return combineUrl(urls.llmAnalyticsPrompt(promptName), cleanPromptSearchParams(searchParams, version, versionId))
        .url
}

function PromptAnalyticsScopeControls({
    analyticsScope,
    setAnalyticsScope,
}: {
    analyticsScope: PromptAnalyticsScope
    setAnalyticsScope: (analyticsScope: PromptAnalyticsScope) => void
}): JSX.Element {
    return (
        <div className="flex items-center gap-1 rounded border p-1">
            <LemonButton
                size="xsmall"
                type={analyticsScope === PromptAnalyticsScope.Selected ? 'primary' : 'secondary'}
                onClick={() => setAnalyticsScope(PromptAnalyticsScope.Selected)}
            >
                Selected version
            </LemonButton>
            <LemonButton
                size="xsmall"
                type={analyticsScope === PromptAnalyticsScope.AllVersions ? 'primary' : 'secondary'}
                onClick={() => setAnalyticsScope(PromptAnalyticsScope.AllVersions)}
            >
                All current versions
            </LemonButton>
        </div>
    )
}
