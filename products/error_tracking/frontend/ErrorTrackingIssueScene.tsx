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
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { Metadata } from './issue/Metadata'
import { ISSUE_STATUS_OPTIONS } from './utils'
import { ConnectIssueButton } from './components/ErrorTrackingExternalReference'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useErrorTagRenderer } from './hooks/use-error-tag-renderer'
import { ErrorTrackingIssueScenePanel } from './ErrorTrackingIssueScenePanel'

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
    const { issue, issueLoading, selectedEvent, firstSeenEventLoading } = useValues(errorTrackingIssueSceneLogic)
    const { loadIssue, updateAssignee, updateStatus } = useActions(errorTrackingIssueSceneLogic)
    const tagRenderer = useErrorTagRenderer()
    const hasIntegrations = useFeatureFlag('ERROR_TRACKING_INTEGRATIONS')

    useEffect(() => {
        loadIssue()
    }, [loadIssue])

    return (
        <ErrorTrackingSetupPrompt>
            <PageHeader
                buttons={
                    <div className="flex gap-x-2">
                        {hasIntegrations ? <ConnectIssueButton /> : null}
                        {!issueLoading && issue?.status === 'active' && (
                            <AssigneeSelect
                                assignee={issue?.assignee}
                                onChange={(assignee) => updateAssignee(assignee)}
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
                                onChange={(status) => updateStatus(status)}
                            />
                        )}
                    </div>
                }
            />

            <ErrorTrackingIssueScenePanel />

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
