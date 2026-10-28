import { useActions, useValues } from 'kea'

import { SceneComment } from 'lib/components/Scenes/SceneComment'
import { SceneShareButton } from 'lib/components/Scenes/SceneShareButton'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconFingerprint } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { ScenePanel, ScenePanelDivider, ScenePanelInfoSection, ScenePanelLabel } from '~/layout/scenes/SceneLayout'
import { ScenePanelActionsSection } from '~/layout/scenes/SceneLayout'
import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { ExternalReferences } from '../../../components/ExternalReferences'
import { manageFingerprintsLogic } from '../../../components/FingerprintPreview/manageFingerprintsLogic'
import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'

export const ErrorTrackingIssueScenePanel = ({
    issue,
}: {
    issue: ErrorTrackingRelationalIssue
}): JSX.Element | null => {
    const hasIssueSplitting = useFeatureFlag('ERROR_TRACKING_ISSUE_SPLITTING')

    return issue ? (
        <ScenePanel>
            <ScenePanelInfoSection>
                <SceneActivityIndicator at={issue.first_seen} prefix="First seen" />
                <IssueExternalReference />
            </ScenePanelInfoSection>
            <ScenePanelDivider />
            <ScenePanelActionsSection>
                <SceneComment dataAttrKey="issue" />
                <SceneShareButton
                    dataAttrKey="issue"
                    buttonProps={{
                        fullWidth: true,
                        onClick: () => {
                            void copyToClipboard(urls.absolute(urls.errorTrackingIssue(issue.id)), 'issue link')
                        },
                    }}
                />
                {hasIssueSplitting && <IssueFingerprints />}
            </ScenePanelActionsSection>
        </ScenePanel>
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
    const { openManage } = useActions(manageFingerprintsLogic({ issueId: issue?.id ?? 'no-issue' }))
    return (
        <ButtonPrimitive fullWidth disabled={!issue} onClick={openManage} data-attr="issue-panel-fingerprints">
            <IconFingerprint />
            {`Manage ${issueFingerprintsLoading ? 'fingerprints' : pluralize(issueFingerprints.length, 'fingerprint')}`}
        </ButtonPrimitive>
    )
}
