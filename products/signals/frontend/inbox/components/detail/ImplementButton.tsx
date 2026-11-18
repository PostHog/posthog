import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconCopy, IconPullRequest } from '@posthog/icons'
import { LemonButton, LemonMenuOverlay, LemonSelect, lemonToast } from '@posthog/lemon-ui'

import type { AgentPromptDestination } from 'lib/components/AgentPromptButton'
import { GitHubRepositoryPicker } from 'lib/integrations/GitHubIntegrationHelpers'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import type { ReportTaskEntry } from '../../logics/inboxReportDetailLogic'
import { reportGithubAccessLogic } from '../../logics/reportGithubAccessLogic'
import { SignalReport } from '../../types'
import { buildReportImplementationPrompt } from './buildReportImplementationPrompt'
import { IMPLEMENTATION_AGENTS } from './implementationAgents'
import { ReportGithubConnection } from './ReportGithubConnection'

interface ImplementButtonProps {
    report: SignalReport
    surface?: 'detail_pane' | 'triage_mode'
    position?: 'body' | 'header'
    implementationDisabledReason?: string | null
    reportTaskToOpen?: ReportTaskEntry | null
    openChoicesFromLink?: boolean
    onChoicesOpenedFromLink?: () => void
}

export function ImplementButton({
    report,
    surface = 'detail_pane',
    position = 'body',
    implementationDisabledReason,
    reportTaskToOpen,
    openChoicesFromLink = false,
    onChoicesOpenedFromLink,
}: ImplementButtonProps): JSX.Element {
    const { isCreatingPr, isDiscussing, createPrDisabledReason } = useValues(inboxTaskKickoffLogic)
    const {
        disabledReason: githubDisabledReason,
        repairNeeded,
        connectionOpen,
        failed: githubCheckFailed,
        loading: githubCheckLoading,
        repositoryRequired,
        repositoryIntegrationId,
        selectedRepository,
        githubIntegrations,
    } = useValues(reportGithubAccessLogic({ report, surface }))
    const { retryAccess, setConnectionOpen, setSelectedRepository, setSelectedIntegrationId } = useActions(
        reportGithubAccessLogic({ report, surface })
    )
    const { implementReport, openReportTask } = useActions(inboxTaskKickoffLogic)
    const [instructions, setInstructions] = useState('')
    const [choicesOpen, setChoicesOpen] = useState(false)
    const choicesOpenedFromLink = useRef(false)
    useEffect(() => {
        if (openChoicesFromLink) {
            choicesOpenedFromLink.current = true
            setChoicesOpen(true)
            onChoicesOpenedFromLink?.()
        }
    }, [openChoicesFromLink, onChoicesOpenedFromLink])
    useEffect(() => {
        if (repositoryRequired) {
            setChoicesOpen(true)
        }
    }, [repositoryRequired])
    const reportUrl = `${window.location.origin}${addProjectIdIfMissing(urls.inboxReport('reports', report.id))}`

    const disabledReason =
        createPrDisabledReason ??
        (repairNeeded ? null : githubDisabledReason) ??
        (isDiscussing ? 'Wait for the discussion task to start.' : undefined) ??
        implementationDisabledReason
    const repositoryMissing = repositoryRequired && !selectedRepository

    const captureButtonClick = (buttonAction: 'implement' | 'view_task'): void => {
        captureInboxReportAction({
            report,
            actionType: 'implementation_button_clicked',
            surface,
            extra: { button_action: buttonAction, button_position: position },
        })
    }

    const submit = (note: string): void => {
        if (isCreatingPr || isDiscussing || implementationDisabledReason) {
            return
        }
        if (createPrDisabledReason) {
            lemonToast.error(createPrDisabledReason)
            return
        }
        captureButtonClick('implement')
        if (repairNeeded) {
            setChoicesOpen(false)
            setConnectionOpen(true)
            return
        }
        if (githubDisabledReason) {
            lemonToast.error(githubDisabledReason)
            return
        }
        if (repositoryMissing) {
            setChoicesOpen(true)
            return
        }
        const openedFromLink = choicesOpenedFromLink.current
        // The claim can need a dialog first, which the open choices would sit on top of.
        setChoicesOpen(false)
        choicesOpenedFromLink.current = false
        implementReport(
            report,
            note.trim() || undefined,
            surface,
            openedFromLink,
            repositoryRequired ? selectedRepository : undefined
        )
    }

    const runImplementationPrompt = (agentKey: AgentPromptDestination, run: (prompt: string) => void): void => {
        const prompt = buildReportImplementationPrompt(report, reportUrl)
        captureInboxReportAction({
            report,
            actionType: 'copy_implementation_prompt',
            surface,
            extra: { agent: agentKey },
        })
        run(prompt)
    }

    if (reportTaskToOpen?.task.latest_run) {
        const task = reportTaskToOpen.task
        const run = task.latest_run!
        return (
            <LemonButton
                type="primary"
                size="small"
                className="w-fit"
                to={urls.taskDetail(task.id)}
                onClick={(event) => {
                    event.preventDefault()
                    captureButtonClick('view_task')
                    openReportTask(report, task.id, run.id)
                }}
                tooltip="Open this task in the PostHog AI sidebar"
                data-attr="inbox-report-open-task"
            >
                View task
            </LemonButton>
        )
    }

    return (
        <>
            <LemonButton
                type="primary"
                size="small"
                className="[--lemon-button-hover-depth:0px]"
                icon={<IconPullRequest />}
                onClick={() => submit(instructions)}
                loading={isCreatingPr}
                disabledReason={disabledReason}
                tooltip="Start a PostHog agent to implement this report"
                data-attr={surface === 'triage_mode' ? 'inbox-triage-create-pr' : 'inbox-report-create-pr'}
                sideAction={{
                    tooltip: 'More implementation options',
                    'aria-label': 'More implementation options',
                    'data-attr': 'inbox-report-create-pr-steer',
                    dropdown: {
                        visible: choicesOpen && !connectionOpen,
                        onVisibilityChange: (visible) => {
                            if (!visible) {
                                choicesOpenedFromLink.current = false
                            }
                            setChoicesOpen(visible)
                        },
                        placement: 'bottom-end',
                        closeOnClickInside: false,
                        overlay: (
                            <div className="flex w-128 max-w-[calc(100vw-2rem)] flex-col gap-2 p-2">
                                {repositoryRequired && (
                                    <div className="flex flex-col gap-2">
                                        <span className="text-xs font-semibold text-tertiary">
                                            Select a repository to implement this report
                                        </span>
                                        {githubIntegrations.length > 1 && (
                                            <LemonSelect
                                                value={repositoryIntegrationId}
                                                options={githubIntegrations.map((integration) => ({
                                                    value: integration.id,
                                                    label: integration.display_name,
                                                }))}
                                                onChange={(id) => id != null && setSelectedIntegrationId(id)}
                                                disabledReason={isCreatingPr ? 'Starting implementation' : undefined}
                                                aria-label="GitHub account"
                                            />
                                        )}
                                        {repositoryIntegrationId !== null ? (
                                            <GitHubRepositoryPicker
                                                integrationId={repositoryIntegrationId}
                                                value={selectedRepository}
                                                valueKey="full_name"
                                                onChange={setSelectedRepository}
                                            />
                                        ) : (
                                            <LemonButton
                                                type="secondary"
                                                onClick={() => {
                                                    setChoicesOpen(false)
                                                    setConnectionOpen(true)
                                                }}
                                                data-attr="inbox-report-select-repository-connect"
                                            >
                                                Connect GitHub
                                            </LemonButton>
                                        )}
                                    </div>
                                )}
                                <span className="text-xs font-semibold text-tertiary">
                                    Add instructions for the PostHog agent
                                </span>
                                <LemonTextArea
                                    autoComplete="off"
                                    data-1p-ignore="true"
                                    data-lpignore="true"
                                    data-bwignore="true"
                                    data-protonpass-ignore="true"
                                    data-form-type="other"
                                    value={instructions}
                                    onChange={setInstructions}
                                    onPressEnter={submit}
                                    placeholder="Add instructions for the PostHog agent (optional)"
                                    maxLength={4000}
                                    rows={4}
                                    autoFocus
                                    actions={[
                                        <span key="shortcut" className="text-xs text-tertiary">
                                            Enter to implement, Shift + Enter for a new line
                                        </span>,
                                    ]}
                                />
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                    <LemonButton
                                        type="secondary"
                                        icon={<IconCopy />}
                                        onClick={() =>
                                            runImplementationPrompt('clipboard', (prompt) => {
                                                void copyToClipboard(prompt, 'prompt for your agent')
                                            })
                                        }
                                        data-attr="inbox-report-copy-implementation-prompt"
                                        sideAction={{
                                            tooltip: 'Open prompt in an agent',
                                            'aria-label': 'Open prompt in an agent',
                                            dropdown: {
                                                placement: 'bottom-start',
                                                overlay: (
                                                    <LemonMenuOverlay
                                                        items={IMPLEMENTATION_AGENTS.map((agent) => ({
                                                            key: agent.key,
                                                            label: agent.name,
                                                            icon: agent.icon,
                                                            onClick: () =>
                                                                runImplementationPrompt(agent.key, agent.open),
                                                        }))}
                                                    />
                                                ),
                                            },
                                        }}
                                    >
                                        Copy prompt for your agent
                                    </LemonButton>
                                    {githubCheckFailed && (
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            onClick={retryAccess}
                                            loading={githubCheckLoading}
                                            data-attr={
                                                surface === 'triage_mode'
                                                    ? 'inbox-triage-retry-github'
                                                    : 'inbox-report-retry-github'
                                            }
                                        >
                                            Retry GitHub check
                                        </LemonButton>
                                    )}
                                    <LemonButton
                                        type="primary"
                                        icon={<IconPullRequest />}
                                        onClick={() => submit(instructions)}
                                        loading={isCreatingPr}
                                        disabledReason={
                                            disabledReason ??
                                            (repositoryMissing ? 'Select a repository to continue.' : null)
                                        }
                                        data-attr="inbox-report-create-pr-submit"
                                    >
                                        Implement with PostHog
                                    </LemonButton>
                                </div>
                            </div>
                        ),
                    },
                }}
            >
                {repositoryMissing ? 'Select repository' : 'Implement'}
            </LemonButton>
            <ReportGithubConnection report={report} surface={surface} />
        </>
    )
}
