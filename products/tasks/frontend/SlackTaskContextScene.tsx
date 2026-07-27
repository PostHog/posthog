import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonDivider, LemonInput, LemonTag, Spinner } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { Link } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SlackThreadContextRepoResearchApi, SlackThreadContextRunApi } from './generated/api.schemas'
import { slackTaskContextSceneLogic } from './logics/slackTaskContextSceneLogic'

export const scene: SceneExport = {
    component: SlackTaskContextScene,
    logic: slackTaskContextSceneLogic,
}

export function SlackTaskContextScene(): JSX.Element {
    const { url, result, resultLoading, submissionError, canSubmit } = useValues(slackTaskContextSceneLogic)
    const { setUrl, loadResult, clearResult } = useActions(slackTaskContextSceneLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Slack task context"
                description="Look up the PostHog Task, runs, and Temporal workflows linked to a Slack thread. Restricted to PostHog-internal debugging (team 2)."
                resourceType={{ type: 'task' }}
            />

            <LemonBanner type="info">
                Paste any Slack permalink from inside the thread (parent message or reply). Reply URLs that carry{' '}
                <code>?thread_ts=…</code> resolve to the originating thread. Log URLs expire after ~1 hour.
            </LemonBanner>

            <div className="flex items-end gap-2">
                <LemonInput
                    placeholder="https://posthog.slack.com/archives/C…/p1779956938619299"
                    value={url}
                    onChange={setUrl}
                    onPressEnter={() => {
                        if (canSubmit) {
                            loadResult()
                        }
                    }}
                    className="flex-1"
                    autoFocus
                />
                <LemonButton
                    type="primary"
                    loading={resultLoading}
                    disabledReason={
                        url.trim().length === 0 ? 'Enter a Slack thread URL' : resultLoading ? 'Loading…' : null
                    }
                    onClick={() => loadResult()}
                >
                    Look up
                </LemonButton>
                {(result || submissionError) && !resultLoading ? (
                    <LemonButton type="secondary" onClick={() => clearResult()}>
                        Clear
                    </LemonButton>
                ) : null}
            </div>

            {submissionError ? (
                <LemonBanner type="error">
                    {submissionError.status === 403
                        ? 'This endpoint is restricted to PostHog-internal debugging (team 2).'
                        : submissionError.status === 404
                          ? 'No Slack → task mapping found for that thread.'
                          : submissionError.detail || 'Request failed.'}
                </LemonBanner>
            ) : null}

            {resultLoading ? (
                <div className="flex items-center gap-2 text-muted">
                    <Spinner /> Looking up the thread…
                </div>
            ) : null}

            {result ? <SlackTaskContextResult result={result} /> : null}
        </SceneContent>
    )
}

function SlackTaskContextResult({
    result,
}: {
    result: NonNullable<ReturnType<typeof useValues<typeof slackTaskContextSceneLogic>>['result']>
}): JSX.Element {
    const { thread, task, runs } = result
    return (
        <div className="space-y-4">
            <section>
                <h3 className="mb-2">Thread</h3>
                <KeyValueGrid
                    rows={[
                        ['Channel', thread.channel],
                        ['Thread ts', thread.thread_ts],
                        ['Workspace', thread.slack_workspace_id ?? '—'],
                        ['Mentioning user', thread.mentioning_slack_user_id ?? '—'],
                        [
                            'Slack URL',
                            <Link key="slack-url" to={thread.url} target="_blank">
                                {thread.url}
                            </Link>,
                        ],
                    ]}
                />
            </section>

            <LemonDivider />

            {task ? (
                <section>
                    <h3 className="mb-2">Task</h3>
                    <KeyValueGrid
                        rows={[
                            ['Title', task.title],
                            ['Task ID', <CodeSnippet key="task-id">{task.id}</CodeSnippet>],
                            ['Repository', task.repository ?? <em key="empty">empty (no repo)</em>],
                            ['Origin', task.origin_product],
                            ['Team ID', String(task.team_id)],
                            [
                                'Open in PostHog',
                                <Link key="task-url" to={task.url}>
                                    {task.url}
                                </Link>,
                            ],
                        ]}
                    />
                </section>
            ) : (
                <LemonBanner type="warning">No task is linked to this thread.</LemonBanner>
            )}

            <LemonDivider />

            <section>
                <h3 className="mb-2">Runs ({runs.length})</h3>
                {runs.length === 0 ? (
                    <div className="text-muted">No runs yet.</div>
                ) : (
                    <div className="space-y-4">
                        {runs.map((run, idx) => (
                            <SlackTaskContextRunCard key={run.id} run={run} index={idx + 1} />
                        ))}
                    </div>
                )}
            </section>
        </div>
    )
}

function SlackTaskContextRunCard({ run, index }: { run: SlackThreadContextRunApi; index: number }): JSX.Element {
    return (
        <div className="border rounded p-3">
            <div className="flex items-center justify-between mb-2">
                <h4 className="m-0">
                    Run #{index} <LemonTag size="small">{run.status}</LemonTag>
                </h4>
                <span className="text-muted text-sm">{run.created_at}</span>
            </div>
            <KeyValueGrid
                rows={[
                    ['Run ID', <CodeSnippet key="run-id">{run.id}</CodeSnippet>],
                    [
                        'Open in PostHog',
                        <Link key="task-view" to={run.task_view_url}>
                            {run.task_view_url}
                        </Link>,
                    ],
                    [
                        'Task-processing workflow',
                        <WorkflowLink
                            key="task-processing-wf"
                            id={run.task_processing_workflow_id}
                            url={run.task_processing_workflow_url}
                        />,
                    ],
                    [
                        'Mention workflow',
                        run.mention_workflow_id ? (
                            <WorkflowLink
                                key="mention-wf"
                                id={run.mention_workflow_id}
                                url={run.mention_workflow_url}
                            />
                        ) : (
                            <span key="empty" className="text-muted">
                                Not recorded (run created before this field was persisted).
                            </span>
                        ),
                    ],
                    [
                        'Sandbox',
                        run.sandbox_url ? (
                            <Link key="sandbox" to={run.sandbox_url} target="_blank">
                                {run.sandbox_url}
                            </Link>
                        ) : (
                            <span key="empty" className="text-muted">
                                —
                            </span>
                        ),
                    ],
                    [
                        'PR',
                        run.pr_url ? (
                            <Link key="pr" to={run.pr_url} target="_blank">
                                {run.pr_url}
                            </Link>
                        ) : (
                            <span key="empty" className="text-muted">
                                —
                            </span>
                        ),
                    ],
                    [
                        'Logs (presigned, ~1h)',
                        run.log_url ? (
                            <Link key="log" to={run.log_url} target="_blank">
                                Download JSONL
                            </Link>
                        ) : (
                            <span key="empty" className="text-muted">
                                —
                            </span>
                        ),
                    ],
                    [
                        'Error',
                        run.error_message ? (
                            <code key="err">{run.error_message}</code>
                        ) : (
                            <span key="empty" className="text-muted">
                                —
                            </span>
                        ),
                    ],
                    [
                        'Completed at',
                        run.completed_at ?? (
                            <span key="empty" className="text-muted">
                                — (still running)
                            </span>
                        ),
                    ],
                ]}
            />
            {run.repo_research ? <RepoResearchBlock research={run.repo_research} /> : null}
        </div>
    )
}

function RepoResearchBlock({ research }: { research: SlackThreadContextRepoResearchApi }): JSX.Element {
    return (
        <div className="mt-3 pl-3 border-l-2">
            <div className="text-muted font-semibold mb-1">
                Repo research sandbox <LemonTag size="small">{research.status ?? 'unknown'}</LemonTag>
            </div>
            <p className="text-muted text-xs mb-2">
                This run started from an ambiguous mention, so the discovery agent ran a sandbox to pick the repo.
            </p>
            <KeyValueGrid
                rows={[
                    ['Research run ID', <CodeSnippet key="rr-id">{research.run_id}</CodeSnippet>],
                    [
                        'Open in PostHog',
                        <Link key="rr-view" to={research.task_view_url}>
                            {research.task_view_url}
                        </Link>,
                    ],
                    [
                        'Research workflow',
                        <WorkflowLink
                            key="rr-wf"
                            id={research.task_processing_workflow_id}
                            url={research.task_processing_workflow_url}
                        />,
                    ],
                    [
                        'Sandbox',
                        research.sandbox_url ? (
                            <Link key="rr-sandbox" to={research.sandbox_url} target="_blank">
                                {research.sandbox_url}
                            </Link>
                        ) : (
                            <span key="empty" className="text-muted">
                                —
                            </span>
                        ),
                    ],
                    [
                        'Logs (presigned, ~1h)',
                        research.log_url ? (
                            <Link key="rr-log" to={research.log_url} target="_blank">
                                Download JSONL
                            </Link>
                        ) : (
                            <span key="empty" className="text-muted">
                                —
                            </span>
                        ),
                    ],
                ]}
            />
        </div>
    )
}

function WorkflowLink({ id, url }: { id: string; url: string | null }): JSX.Element {
    if (url) {
        return (
            <Link to={url} target="_blank">
                {id}
            </Link>
        )
    }
    return (
        <span>
            <code>{id}</code>{' '}
            <span className="text-muted text-xs">
                (TEMPORAL_UI_HOST not configured — search Temporal UI by workflow id)
            </span>
        </span>
    )
}

function KeyValueGrid({ rows }: { rows: Array<[string, React.ReactNode]> }): JSX.Element {
    return (
        <div className="grid grid-cols-[180px_1fr] gap-y-1 gap-x-3">
            {rows.map(([label, value]) => (
                <ContextRow key={label} label={label}>
                    {value}
                </ContextRow>
            ))}
        </div>
    )
}

function ContextRow({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <>
            <div className="text-muted font-semibold">{label}</div>
            <div className="break-all">{children}</div>
        </>
    )
}

export default SlackTaskContextScene
