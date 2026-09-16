import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCopy, IconLogomark, IconPullRequest } from '@posthog/icons'
import { LemonButton, LemonMenuOverlay, lemonToast } from '@posthog/lemon-ui'

import {
    buildClaudeCodeDeepLink,
    buildCodexDeepLink,
    buildCursorDeepLink,
    buildPostHogCodeDeepLink,
} from 'lib/components/AgentPromptButton'
import type { AgentPromptDestination } from 'lib/components/AgentPromptButton'
import { AgentLogo, claudeLogo, cursorLogo, openaiLogo } from 'lib/components/AgentPromptButton/AgentLogo'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { ImplementationSlotClaim, inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { buildReportImplementationPrompt } from './buildReportImplementationPrompt'

const SLOT_CLAIM_DISABLED_REASON: Record<ImplementationSlotClaim, string> = {
    in_flight: 'A pull request run is already in progress for this report. Open it in the task log to follow it.',
    shipped_pr: 'This report already has a pull request. Open it in the task log to continue it.',
}

const IMPLEMENTATION_AGENTS: {
    key: AgentPromptDestination
    name: string
    icon: JSX.Element
    buildDeepLink: (prompt: string) => string
}[] = [
    {
        key: 'posthog-code',
        name: 'PostHog Desktop',
        icon: <IconLogomark />,
        buildDeepLink: buildPostHogCodeDeepLink,
    },
    {
        key: 'claude-code',
        name: 'Claude Code',
        icon: <AgentLogo logo={claudeLogo} />,
        buildDeepLink: buildClaudeCodeDeepLink,
    },
    {
        key: 'cursor',
        name: 'Cursor',
        icon: <AgentLogo logo={cursorLogo} logoClassName="dark:invert" />,
        buildDeepLink: buildCursorDeepLink,
    },
    {
        key: 'codex',
        name: 'Codex',
        icon: <AgentLogo logo={openaiLogo} />,
        buildDeepLink: buildCodexDeepLink,
    },
]

export function ImplementButton({ report }: { report: SignalReport }): JSX.Element {
    const { isCreatingPr, isDiscussing, createPrDisabledReason } = useValues(inboxTaskKickoffLogic)
    const { implementationSlotClaim, reportTaskToOpen } = useValues(
        inboxReportDetailLogic({ reportId: report.id, report })
    )
    const { createPrFromReport, openReportTask } = useActions(inboxTaskKickoffLogic)
    const [instructions, setInstructions] = useState('')
    const reportUrl = `${window.location.origin}${addProjectIdIfMissing(urls.inboxReport('reports', report.id))}`

    const disabledReason =
        createPrDisabledReason ??
        (isDiscussing ? 'Wait for the discussion task to start.' : undefined) ??
        (implementationSlotClaim ? SLOT_CLAIM_DISABLED_REASON[implementationSlotClaim] : undefined)

    const submit = (note: string): void => {
        if (isCreatingPr || isDiscussing || implementationSlotClaim) {
            return
        }
        if (createPrDisabledReason) {
            lemonToast.error(createPrDisabledReason)
            return
        }
        const trimmed = note.trim()
        captureInboxReportAction({
            report,
            actionType: 'create_pr',
            surface: 'detail_pane',
            extra: { has_feedback: trimmed.length > 0 },
        })
        createPrFromReport(report, trimmed || undefined)
    }

    const runImplementationPrompt = (agentKey: AgentPromptDestination, run: (prompt: string) => void): void => {
        const prompt = buildReportImplementationPrompt(report, reportUrl)
        captureInboxReportAction({
            report,
            actionType: 'copy_implementation_prompt',
            surface: 'detail_pane',
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
                to={urls.taskDetail(task.id)}
                onClick={(event) => {
                    event.preventDefault()
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
        <LemonButton
            type="primary"
            size="small"
            className="[--lemon-button-hover-depth:0px]"
            icon={<IconPullRequest />}
            onClick={() => submit('')}
            loading={isCreatingPr}
            disabledReason={disabledReason}
            tooltip="Implement this report with PostHog"
            data-attr="inbox-report-create-pr"
            sideAction={{
                tooltip: 'More implementation options',
                'aria-label': 'More implementation options',
                'data-attr': 'inbox-report-create-pr-steer',
                dropdown: {
                    placement: 'bottom-end',
                    closeOnClickInside: false,
                    overlay: (
                        <div className="flex w-128 flex-col gap-2 p-2">
                            <span className="text-xs font-semibold text-tertiary">
                                Add instructions for the PostHog agent
                            </span>
                            <LemonTextArea
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
                                                            runImplementationPrompt(agent.key, (prompt) => {
                                                                window.open(agent.buildDeepLink(prompt), '_blank')
                                                            }),
                                                    }))}
                                                />
                                            ),
                                        },
                                    }}
                                >
                                    Copy prompt for your agent
                                </LemonButton>
                                <LemonButton
                                    type="primary"
                                    icon={<IconPullRequest />}
                                    onClick={() => submit(instructions)}
                                    loading={isCreatingPr}
                                    disabledReason={disabledReason}
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
            Implement
        </LemonButton>
    )
}
