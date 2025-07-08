import './ErrorTracking.scss'

import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { useEffect } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { AssigneeIconDisplay, AssigneeLabelDisplay } from './components/Assignee/AssigneeDisplay'
import { AssigneeSelect } from './components/Assignee/AssigneeSelect'
import { ErrorFilters } from './components/ErrorFilters'
import { ErrorTrackingSetupPrompt } from './components/ErrorTrackingSetupPrompt/ErrorTrackingSetupPrompt'
import { ExceptionCard } from './components/ExceptionCard'
import { GenericSelect } from './components/GenericSelect'
import { IssueStatus, StatusIndicator } from './components/Indicator'
import { issueActionsLogic } from './components/IssueActions/issueActionsLogic'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { useErrorTagRenderer } from './hooks/use-error-tag-renderer'
import { Metadata } from './issue/Metadata'
import { ISSUE_STATUS_OPTIONS } from './utils'
import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SidePanelTab } from '~/types'
import { SidePanelDiscussionIcon } from '~/layout/navigation-3000/sidepanel/panels/discussion/SidePanelDiscussion'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

export const scene: SceneExport = {
    component: ErrorTrackingIssueScene,
    logic: errorTrackingIssueSceneLogic,
    paramsToProps: ({
        params: { id },
        searchParams: { fingerprint },
    }): (typeof errorTrackingIssueSceneLogic)['props'] => ({ id, fingerprint }),
}

export const STATUS_LABEL: Record<ErrorTrackingIssue['status'], string> = {
    active: 'Active',
    archived: 'Archived',
    resolved: 'Resolved',
    pending_release: 'Pending release',
    suppressed: 'Suppressed',
}

export function ErrorTrackingIssueScene(): JSX.Element {
    const { issue, issueId, issueLoading, selectedEvent, firstSeenEventLoading } =
        useValues(errorTrackingIssueSceneLogic)
    const { loadIssue } = useActions(errorTrackingIssueSceneLogic)
    const { updateIssueAssignee, updateIssueStatus } = useActions(issueActionsLogic)
    const tagRenderer = useErrorTagRenderer()
    const hasDiscussions = useFeatureFlag('DISCUSSIONS')
    const { openSidePanel } = useActions(sidePanelLogic)

    useEffect(() => {
        loadIssue()
    }, [loadIssue])

    return (
        <ErrorTrackingSetupPrompt>
            <PageHeader
                buttons={
                    <div className="flex gap-x-2">
                        {hasDiscussions && (
                            <LemonButton
                                type="secondary"
                                onClick={() => openSidePanel(SidePanelTab.Discussion)}
                                icon={<SidePanelDiscussionIcon />}
                            >
                                Comment
                            </LemonButton>
                        )}
                        {!issueLoading && issue?.status === 'active' && (
                            <AssigneeSelect
                                assignee={issue?.assignee}
                                onChange={(assignee) => updateIssueAssignee(issueId, assignee)}
                            >
                                {(displayAssignee) => (
                                    <LemonButton
                                        type="secondary"
                                        icon={<AssigneeIconDisplay assignee={displayAssignee} />}
                                    >
                                        <AssigneeLabelDisplay assignee={displayAssignee} placeholder="Unassigned" />
                                    </LemonButton>
                                )}
                            </AssigneeSelect>
                        )}
                        {!issueLoading && (
                            <GenericSelect
                                size="small"
                                current={issue?.status}
                                values={ISSUE_STATUS_OPTIONS}
                                placeholder="Mark as"
                                renderValue={(value) => (
                                    <StatusIndicator status={value as IssueStatus} size="small" withTooltip={true} />
                                )}
                                onChange={(status) => updateIssueStatus(issueId, status)}
                            />
                        )}
                    </div>
                }
            />
            <div className="ErrorTrackingIssue space-y-2">
                <ExceptionCard
                    issue={issue ?? undefined}
                    issueLoading={issueLoading}
                    event={selectedEvent ?? undefined}
                    eventLoading={firstSeenEventLoading}
                    label={tagRenderer(selectedEvent)}
                />
                <ErrorFilters.Root>
                    <ErrorFilters.DateRange />
                    <ErrorFilters.FilterGroup />
                    <ErrorFilters.InternalAccounts />
                </ErrorFilters.Root>
                <Metadata />
            </div>
        </ErrorTrackingSetupPrompt>
    )
}
