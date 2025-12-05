import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { SceneComment } from 'lib/components/Scenes/SceneComment'
import { SceneShareButton } from 'lib/components/Scenes/SceneShareButton'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconFingerprint } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { pluralize } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { ScenePanel, ScenePanelDivider, ScenePanelInfoSection, ScenePanelLabel } from '~/layout/scenes/SceneLayout'
import { ScenePanelActionsSection } from '~/layout/scenes/SceneLayout'
import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { ExternalReferences } from '../../../components/ExternalReferences'
import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { IssueCohort } from './IssueCohort'

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
                <IssueCohort issue={issue} />
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
    return (
        <Link to={issue ? urls.errorTrackingIssueFingerprints(issue.id) : undefined}>
            <ButtonPrimitive fullWidth>
                <IconFingerprint />
                {`Manage ${issueFingerprintsLoading ? 'fingerprints' : pluralize(issueFingerprints.length, 'fingerprint')}`}
            </ButtonPrimitive>
        </Link>
    )
}
