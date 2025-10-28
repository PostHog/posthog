import { useActions, useValues } from 'kea'

import { Link, Spinner } from '@posthog/lemon-ui'

import { SceneTextInput } from 'lib/components/Scenes/SceneTextInput'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { pluralize } from 'lib/utils'
import { urls } from 'scenes/urls'

import { ScenePanelDivider, ScenePanelLabel } from '~/layout/scenes/SceneLayout'

import { MiniBreakdowns } from 'products/error_tracking/frontend/components/Breakdowns/MiniBreakdowns'

import { ExternalReferences } from '../../../components/ExternalReferences'
import { IssueTasks } from '../../../components/IssueTasks'
import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { BaseActions } from './BaseActions'
import { IssueAssigneeSelect } from './IssueAssigneeSelect'
import { IssueStatusSelect } from './IssueStatusSelect'
import { SimilarIssuesList } from './SimilarIssuesList'

const RESOURCE_TYPE = 'issue'

export const ErrorTrackingIssueScenePanel = ({ showActions = true }: { showActions?: boolean }): JSX.Element | null => {
    const { issue } = useValues(errorTrackingIssueSceneLogic)
    const { updateName, updateAssignee, updateStatus } = useActions(errorTrackingIssueSceneLogic)
    const hasTasks = useFeatureFlag('TASKS')
    const hasIssueSplitting = useFeatureFlag('ERROR_TRACKING_ISSUE_SPLITTING')
    const hasSimilarIssues = useFeatureFlag('ERROR_TRACKING_RELATED_ISSUES')
    const hasNewIssueLayout = useFeatureFlag('ERROR_TRACKING_ISSUE_LAYOUT_V2')

    return issue ? (
        <div className="flex flex-col gap-2 @container">
            {showActions && (
                <>
                    <BaseActions issueId={issue.id} resourceType={RESOURCE_TYPE} />
                    <ScenePanelDivider />
                </>
            )}

            <SceneTextInput
                name="name"
                defaultValue={issue.name ?? ''}
                onSave={updateName}
                dataAttrKey={RESOURCE_TYPE}
            />

            <IssueStatusSelect status={issue.status} onChange={updateStatus} />
            <IssueAssigneeSelect
                assignee={issue.assignee}
                onChange={updateAssignee}
                disabled={issue.status != 'active'}
            />
            <IssueExternalReference />
            {hasIssueSplitting && <IssueFingerprints />}
            {hasTasks && <IssueTasks />}
            <SceneActivityIndicator at={issue.first_seen} prefix="First seen" />
            {hasNewIssueLayout && <IssueBreakdowns />}
            {hasSimilarIssues && <SimilarIssuesList />}
        </div>
    ) : null
}

const IssueExternalReference = (): JSX.Element => {
    return (
        <ScenePanelLabel title="External references">
            <ExternalReferences />
        </ScenePanelLabel>
    )
}

const IssueFingerprints = (): JSX.Element => {
    const { issue, issueFingerprints, issueFingerprintsLoading } = useValues(errorTrackingIssueSceneLogic)
    return (
        <ScenePanelLabel title="Fingerprints">
            <Link to={issue ? urls.errorTrackingIssueFingerprints(issue.id) : undefined}>
                <ButtonPrimitive fullWidth menuItem variant="panel">
                    {issueFingerprintsLoading ? <Spinner /> : `${pluralize(issueFingerprints.length, 'fingerprint')}`}
                </ButtonPrimitive>
            </Link>
        </ScenePanelLabel>
    )
}

const IssueBreakdowns = (): JSX.Element => {
    return (
        <ScenePanelLabel title="Breakdowns">
            <MiniBreakdowns />
        </ScenePanelLabel>
    )
}
