import { useActions, useValues } from 'kea'

import { IconComment, IconShare } from '@posthog/icons'
import { Link, Spinner } from '@posthog/lemon-ui'

import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { pluralize } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { ScenePanel, ScenePanelDivider, ScenePanelLabel } from '~/layout/scenes/SceneLayout'
import { ScenePanelActionsSection } from '~/layout/scenes/SceneLayout'
import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'
import { SidePanelTab } from '~/types'

import { ExternalReferences } from '../../../components/ExternalReferences'
import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { IssueCohort } from './IssueCohort'

export const ErrorTrackingIssueScenePanel = ({
    issue,
}: {
    issue: ErrorTrackingRelationalIssue
}): JSX.Element | null => {
    const { openSidePanel } = useActions(sidePanelLogic)
    const hasIssueSplitting = useFeatureFlag('ERROR_TRACKING_ISSUE_SPLITTING')

    return issue ? (
        <ScenePanel>
            <ScenePanelActionsSection>
                <div className="grid grid-cols-2 gap-1">
                    <ButtonPrimitive
                        onClick={() => openSidePanel(SidePanelTab.Discussion)}
                        tooltip="Comment"
                        menuItem
                        className="justify-center"
                    >
                        <IconComment />
                        <span className="hidden @[200px]:block">Comment</span>
                    </ButtonPrimitive>

                    <ButtonPrimitive
                        onClick={() => {
                            void copyToClipboard(
                                window.location.origin + urls.errorTrackingIssue(issue.id),
                                'issue link'
                            )
                        }}
                        tooltip="Share"
                        data-attr={`issue-share`}
                        menuItem
                        className="justify-center"
                    >
                        <IconShare />
                        <span className="hidden @[200px]:block">Share</span>
                    </ButtonPrimitive>
                </div>
            </ScenePanelActionsSection>
            <ScenePanelDivider />
            <IssueExternalReference />
            <IssueCohort issue={issue} />
            {hasIssueSplitting && <IssueFingerprints />}
            <SceneActivityIndicator at={issue.first_seen} prefix="First seen" />
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
        <ScenePanelLabel title="Fingerprints">
            <Link to={issue ? urls.errorTrackingIssueFingerprints(issue.id) : undefined}>
                <ButtonPrimitive fullWidth menuItem variant="panel">
                    {issueFingerprintsLoading ? <Spinner /> : `${pluralize(issueFingerprints.length, 'fingerprint')}`}
                </ButtonPrimitive>
            </Link>
        </ScenePanelLabel>
    )
}
