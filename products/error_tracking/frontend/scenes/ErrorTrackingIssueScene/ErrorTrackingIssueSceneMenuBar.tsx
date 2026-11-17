import { useActions, useValues } from 'kea'

import { IconCopy, IconPlusSmall, IconRewindPlay, IconSend, IconSparkles, IconUser } from '@posthog/icons'

import { SceneComment } from 'lib/components/Scenes/SceneComment'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconFingerprint } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'
import { ErrorTrackingIssue, ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { messageAudienceAccessDisabledReason } from 'products/workflows/frontend/MessageAudience/messageAudience'

import { ExternalReferences } from '../../components/ExternalReferences'
import { manageFingerprintsLogic } from '../../components/FingerprintPreview/manageFingerprintsLogic'
import { getIssueStatusConfig } from '../../components/Indicators'
import { issueActionsLogic } from '../../components/IssueActions/issueActionsLogic'
import { ISSUE_SEVERITY_OPTIONS, IssueSeverity } from '../../components/IssueSeverityTag'
import { IssueStatusButton } from '../../components/IssueStatusButton'
import { IssueStatusSelect } from '../../components/IssueStatusSelect'
import { ISSUE_STATUS_OPTIONS } from '../../utils'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { openIssueWorkflow } from './issueWorkflow'
import { issueAffectedBroadcastLogic } from './ScenePanel/issueAffectedBroadcastLogic'
import { IssueAssigneeSelect } from './ScenePanel/IssueAssigneeSelect'

const RESOURCE_TYPE = 'error-tracking-issue'

interface ErrorTrackingIssueSceneMenuBarProps {
    issue: ErrorTrackingRelationalIssue
    openRecordings: () => void
    setUpVisionScanner: () => void
}

export function ErrorTrackingIssueSceneMenuBar(props: ErrorTrackingIssueSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <ErrorTrackingIssueSceneMenuBarInner {...props} /> : null
}

function ErrorTrackingIssueSceneMenuBarInner({
    issue,
    openRecordings,
    setUpVisionScanner,
}: ErrorTrackingIssueSceneMenuBarProps): JSX.Element {
    const hasIssueSplitting = useFeatureFlag('ERROR_TRACKING_ISSUE_SPLITTING')
    const { updateAssignee, updateSeverity, updateStatus } = useActions(errorTrackingIssueSceneLogic)
    const { severityUpdateInFlightIds } = useValues(issueActionsLogic)
    const { openManage } = useActions(manageFingerprintsLogic({ issueId: issue.id }))
    const { openModal: openEmailAffected } = useActions(
        issueAffectedBroadcastLogic({ issueId: issue.id, issueName: issue.name })
    )
    const emailDisabledReason = messageAudienceAccessDisabledReason() ?? undefined
    const assigneeSelect = (
        <IssueAssigneeSelect assignee={issue.assignee} onChange={updateAssignee} disabled={issue.status != 'active'} />
    )

    const actions: SceneAction[] = [
        ...(issue.name
            ? ([
                  {
                      group: 'file',
                      section: 'create',
                      type: 'submenu',
                      id: `${RESOURCE_TYPE}-menubar-create`,
                      label: 'Create',
                      icon: <IconPlusSmall />,
                      items: [
                          {
                              // pinned: data-attr values are wire strings
                              id: 'error-tracking-scan-with-vision',
                              label: 'Set up a scanner to watch these',
                              icon: <IconSparkles className="text-ai" />,
                              onSelect: setUpVisionScanner,
                          },
                          {
                              id: 'error-tracking-issue-email-affected',
                              label: 'Email people affected',
                              icon: <IconSend />,
                              opensFloatingUi: true,
                              disabledReason: emailDisabledReason,
                              onSelect: openEmailAffected,
                          },
                          {
                              id: 'error-tracking-issue-start-workflow',
                              label: 'Email anyone who hits this',
                              icon: <IconSend />,
                              disabledReason: emailDisabledReason,
                              onSelect: () => openIssueWorkflow(issue.id),
                          },
                      ],
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'file',
            id: `${RESOURCE_TYPE}-menubar-copy-link`,
            label: 'Copy link',
            icon: <IconCopy />,
            onSelect: () => void copyToClipboard(urls.absolute(urls.errorTrackingIssue(issue.id)), 'issue link'),
        },
        {
            group: 'edit',
            section: 'status',
            id: `${RESOURCE_TYPE}-menubar-resolve`,
            label: issue.status === 'active' ? 'Resolve' : 'Reopen',
            onSelect: () => updateStatus(issue.status === 'active' ? 'resolved' : 'active'),
            pinned: {
                order: 1,
                variant: 'primary',
                render: () => <IssueStatusButton status={issue.status} onChange={updateStatus} />,
            },
        },
        {
            group: 'edit',
            type: 'radio',
            id: `${RESOURCE_TYPE}-menubar-status`,
            label: 'Status',
            value: issue.status,
            options: ISSUE_STATUS_OPTIONS.map((status) => ({
                value: status,
                label: getIssueStatusConfig(status).label,
            })),
            onValueChange: (status) => {
                if (status !== issue.status) {
                    updateStatus(status as ErrorTrackingIssue['status'])
                }
            },
            pinned: {
                order: 2,
                variant: 'secondary',
                render: () => <IssueStatusSelect status={issue.status} onChange={updateStatus} size="default" />,
            },
        },
        {
            group: 'edit',
            type: 'radio',
            id: `${RESOURCE_TYPE}-menubar-severity`,
            label: 'Severity',
            value: issue.severity ?? '',
            options: ISSUE_SEVERITY_OPTIONS.map((option) => ({
                value: option.value,
                label: option.label,
                disabledReason: severityUpdateInFlightIds.includes(issue.id) ? 'Saving severity' : undefined,
            })),
            onValueChange: (severity) => updateSeverity(severity as IssueSeverity),
        },
        ...(hasIssueSplitting
            ? ([
                  {
                      group: 'edit',
                      section: 'fingerprints',
                      id: `${RESOURCE_TYPE}-menubar-fingerprints`,
                      label: 'Manage fingerprints',
                      icon: <IconFingerprint />,
                      opensFloatingUi: true,
                      onSelect: openManage,
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-view-recordings`,
            label: 'View recordings',
            icon: <IconRewindPlay />,
            onSelect: openRecordings,
        },
        {
            group: 'metadata',
            type: 'panel',
            id: `${RESOURCE_TYPE}-menubar-assignee`,
            label: 'Assignee',
            icon: <IconUser />,
            disabledReason: issue.status != 'active' ? 'Only an active issue can be assigned' : undefined,
            render: () => assigneeSelect,
            pinned: { order: 3, variant: 'secondary', render: () => assigneeSelect },
        },
        {
            group: 'metadata',
            type: 'panel',
            id: `${RESOURCE_TYPE}-menubar-metadata`,
            label: 'Metadata',
            render: () => (
                <>
                    <SceneActivityIndicator at={issue.first_seen} prefix="First seen" />
                    <ScenePanelLabel title="External references">
                        <ExternalReferences />
                    </ScenePanelLabel>
                    <SceneComment dataAttrKey="issue" />
                </>
            ),
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} className="shrink-0" />
}
