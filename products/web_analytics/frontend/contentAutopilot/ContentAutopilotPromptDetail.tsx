import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'

import { ContentAutopilotPromptActiveSwitch } from './ContentAutopilotPromptActiveSwitch'
import { ContentAutopilotPromptAnswer } from './ContentAutopilotPromptAnswer'
import { ContentAutopilotPromptArchiveBanner } from './ContentAutopilotPromptArchiveBanner'
import { ContentAutopilotPromptChecks } from './ContentAutopilotPromptChecks'
import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'
import { ContentAutopilotPromptEngineSummary } from './ContentAutopilotPromptEngineSummary'
import { ContentAutopilotPromptHistoryGrid } from './ContentAutopilotPromptHistoryGrid'
import { ContentAutopilotPromptVersions } from './ContentAutopilotPromptVersions'

export const ContentAutopilotPromptDetail = (): JSX.Element | null => {
    const { promptId, prompt, stats, historyGrid, lastCheckedAt, detailError, archiveConfirming } = useValues(
        contentAutopilotPromptDetailLogic
    )
    const { closePromptDetail, openPromptDetail, setArchiveConfirming } = useActions(contentAutopilotPromptDetailLogic)

    if (!promptId) {
        return null
    }

    if (detailError === 'not_found') {
        return (
            <LemonModal isOpen onClose={closePromptDetail} title="Prompt not found" width={640}>
                <p className="m-0">
                    This prompt isn't in the project's prompt set anymore. Close this and refresh the list.
                </p>
            </LemonModal>
        )
    }

    return (
        <LemonModal isOpen onClose={closePromptDetail} title={prompt?.prompt ?? 'Loading prompt'} width={960}>
            {detailError === 'failed' ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: () => openPromptDetail(promptId) }}>
                    Couldn't load this prompt. Try again, and if it keeps happening contact support.
                </LemonBanner>
            ) : !prompt || !stats || !historyGrid ? (
                <div className="flex flex-col gap-3">
                    <LemonSkeleton className="h-8 w-1/2" />
                    <LemonSkeleton className="h-24 w-full" />
                    <LemonSkeleton className="h-40 w-full" />
                </div>
            ) : (
                <div className="flex flex-col gap-6">
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
                        {prompt.topic ? (
                            <LemonTag>{prompt.topic}</LemonTag>
                        ) : (
                            <LemonTag type="muted">No topic</LemonTag>
                        )}
                        <LemonTag type="muted">Version {prompt.current_version}</LemonTag>
                        {prompt.archived_at ? (
                            <LemonTag type="muted">Archived</LemonTag>
                        ) : (
                            <ContentAutopilotPromptActiveSwitch
                                promptId={prompt.id}
                                active={prompt.active}
                                label="Active"
                            />
                        )}
                        <span className="text-muted">
                            Last checked {lastCheckedAt ? <TZLabel time={lastCheckedAt} /> : 'never'}
                        </span>
                        <span className="text-muted">{pluralize(stats.total_checks, 'check')} in total</span>
                        {prompt.archived_at ? null : (
                            <LemonButton
                                size="small"
                                type="secondary"
                                status="danger"
                                className="ml-auto"
                                onClick={() => setArchiveConfirming(true)}
                                disabledReason={archiveConfirming ? 'Confirm or cancel below' : undefined}
                                data-attr="content-autopilot-prompt-archive"
                            >
                                Archive
                            </LemonButton>
                        )}
                    </div>
                    <ContentAutopilotPromptArchiveBanner />
                    {prompt.version_count > 1 ? (
                        <section className="flex flex-col gap-2">
                            <h4 className="m-0">Versions</h4>
                            <ContentAutopilotPromptVersions promptId={prompt.id} />
                        </section>
                    ) : null}

                    {stats.engines.length === 0 ? (
                        <p className="m-0 text-muted">
                            This prompt hasn't run yet.{' '}
                            {prompt.active
                                ? 'It runs in the next daily check.'
                                : 'Turn it on to include it in the daily check.'}
                        </p>
                    ) : (
                        <>
                            <section className="flex flex-col gap-2">
                                <h4 className="m-0">Citation rate by engine</h4>
                                <ContentAutopilotPromptEngineSummary engines={stats.engines} />
                            </section>
                            <section className="flex flex-col gap-2">
                                <h4 className="m-0">Last 30 days</h4>
                                <ContentAutopilotPromptHistoryGrid grid={historyGrid} />
                            </section>
                            <section className="flex flex-col gap-2">
                                <h4 className="m-0">Answers</h4>
                                <ContentAutopilotPromptAnswer />
                            </section>
                            <section className="flex flex-col gap-2">
                                <h4 className="m-0">All checks</h4>
                                <ContentAutopilotPromptChecks />
                            </section>
                        </>
                    )}
                </div>
            )}
        </LemonModal>
    )
}
