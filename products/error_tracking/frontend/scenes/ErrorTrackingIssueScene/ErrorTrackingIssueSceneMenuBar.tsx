import { useActions, useValues } from 'kea'

import { IconCopy, IconRewindPlay, IconSend, IconSparkles } from '@posthog/icons'

import { SceneComment } from 'lib/components/Scenes/SceneComment'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconFingerprint } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import {
    SceneMenuBar,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarPopover,
} from '~/layout/scenes/components/SceneMenuBar'
import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'
import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { messageAudienceAccessDisabledReason } from 'products/workflows/frontend/MessageAudience/messageAudience'

import { ExternalReferences } from '../../components/ExternalReferences'
import { manageFingerprintsLogic } from '../../components/FingerprintPreview/manageFingerprintsLogic'
import { issueActionsLogic } from '../../components/IssueActions/issueActionsLogic'
import { IssueSeveritySelect } from '../../components/IssueSeveritySelect'
import { IssueStatusSelect } from '../../components/IssueStatusSelect'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { openIssueWorkflow } from './issueWorkflow'
import { issueAffectedBroadcastLogic } from './ScenePanel/issueAffectedBroadcastLogic'
import { IssueAssigneeSelect } from './ScenePanel/IssueAssigneeSelect'

interface ErrorTrackingIssueSceneMenuBarProps {
    issue: ErrorTrackingRelationalIssue
    onViewRecordings: () => void
    onSetUpVisionScanner: () => void
}

export function ErrorTrackingIssueSceneMenuBar(props: ErrorTrackingIssueSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <ErrorTrackingIssueSceneMenuBarInner {...props} /> : null
}

function ErrorTrackingIssueSceneMenuBarInner({
    issue,
    onViewRecordings,
    onSetUpVisionScanner,
}: ErrorTrackingIssueSceneMenuBarProps): JSX.Element {
    const hasIssueSplitting = useFeatureFlag('ERROR_TRACKING_ISSUE_SPLITTING')
    const { updateAssignee, updateSeverity, updateStatus } = useActions(errorTrackingIssueSceneLogic)
    const { severityUpdateInFlightIds } = useValues(issueActionsLogic)
    const { openManage } = useActions(manageFingerprintsLogic({ issueId: issue.id }))
    const { openModal } = useActions(issueAffectedBroadcastLogic({ issueId: issue.id, issueName: issue.name }))
    const emailDisabledReason = messageAudienceAccessDisabledReason()

    return (
        <SceneMenuBar className="shrink-0">
            <SceneMenuBarMenu label="File" dataAttr="error-tracking-issue-menubar-file">
                <SceneMenuBarItem
                    onClick={() => void copyToClipboard(urls.absolute(urls.errorTrackingIssue(issue.id)), 'issue link')}
                    data-attr="error-tracking-issue-menubar-copy-link"
                >
                    <IconCopy />
                    Copy link
                </SceneMenuBarItem>
                <SceneMenuBarItem
                    onClick={openModal}
                    disabled={!!emailDisabledReason}
                    tooltip={emailDisabledReason ?? undefined}
                    opensFloatingUi
                    data-attr="error-tracking-issue-menubar-email-affected"
                >
                    <IconSend />
                    Email people affected
                </SceneMenuBarItem>
                <SceneMenuBarItem
                    onClick={() => openIssueWorkflow(issue.id)}
                    disabled={!!emailDisabledReason}
                    tooltip={emailDisabledReason ?? undefined}
                    data-attr="error-tracking-issue-menubar-start-workflow"
                >
                    <IconSend />
                    Email anyone who hits this
                </SceneMenuBarItem>
            </SceneMenuBarMenu>
            <SceneMenuBarPopover label="Edit" dataAttr="error-tracking-issue-menubar-edit">
                <div className="flex flex-col gap-2">
                    <ScenePanelLabel title="Status">
                        <IssueStatusSelect status={issue.status} onChange={updateStatus} size="default" />
                    </ScenePanelLabel>
                    <ScenePanelLabel title="Severity">
                        <IssueSeveritySelect
                            severity={issue.severity}
                            onChange={updateSeverity}
                            loading={severityUpdateInFlightIds.includes(issue.id)}
                            size="default"
                        />
                    </ScenePanelLabel>
                    <ScenePanelLabel title="Assignee">
                        <IssueAssigneeSelect
                            assignee={issue.assignee}
                            onChange={updateAssignee}
                            disabled={issue.status !== 'active'}
                        />
                    </ScenePanelLabel>
                    {hasIssueSplitting && (
                        <ButtonPrimitive
                            fullWidth
                            onClick={openManage}
                            data-attr="error-tracking-issue-menubar-fingerprints"
                        >
                            <IconFingerprint />
                            Manage fingerprints
                        </ButtonPrimitive>
                    )}
                </div>
            </SceneMenuBarPopover>
            <SceneMenuBarMenu label="View" dataAttr="error-tracking-issue-menubar-view">
                <SceneMenuBarItem onClick={onViewRecordings} data-attr="error-tracking-issue-menubar-view-recordings">
                    <IconRewindPlay />
                    View recordings
                </SceneMenuBarItem>
                {issue.name && (
                    <SceneMenuBarItem
                        onClick={onSetUpVisionScanner}
                        data-attr="error-tracking-issue-menubar-scan-with-vision"
                    >
                        <IconSparkles />
                        Set up a scanner to watch these
                    </SceneMenuBarItem>
                )}
            </SceneMenuBarMenu>
            <SceneMenuBarPopover label="Metadata" dataAttr="error-tracking-issue-menubar-metadata">
                <div className="flex flex-col gap-2">
                    <SceneActivityIndicator at={issue.first_seen} prefix="First seen" />
                    <ScenePanelLabel title="External references">
                        <ExternalReferences />
                    </ScenePanelLabel>
                    <SceneComment dataAttrKey="issue" />
                </div>
            </SceneMenuBarPopover>
        </SceneMenuBar>
    )
}
