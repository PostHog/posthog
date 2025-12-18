import { useValues } from 'kea'
import { useState } from 'react'

import { IconMessage } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { SceneComment } from 'lib/components/Scenes/SceneComment'
import { SceneShareButton } from 'lib/components/Scenes/SceneShareButton'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconFingerprint } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { pluralize } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { QuickSurveyModal } from 'scenes/surveys/QuickSurveyModal'
import { QuickSurveyType } from 'scenes/surveys/quick-create/types'
import { urls } from 'scenes/urls'

import { ScenePanel, ScenePanelDivider, ScenePanelInfoSection, ScenePanelLabel } from '~/layout/scenes/SceneLayout'
import { ScenePanelActionsSection } from '~/layout/scenes/SceneLayout'
import { ErrorTrackingRelationalIssue, ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

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
                <CreateSurveyButton />
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

const CreateSurveyButton = (): JSX.Element | null => {
    const { issue } = useValues(errorTrackingIssueSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const [showSurveyModal, setShowSurveyModal] = useState(false)

    const exceptionType = issue?.name
    const exceptionMessage = issue?.description

    const showSurveyButton = featureFlags[FEATURE_FLAGS.SURVEYS_ERROR_TRACKING_CROSS_SELL] && exceptionType

    if (!showSurveyButton) {
        return null
    }
    return (
        <>
            <ButtonPrimitive
                fullWidth
                onClick={() => {
                    setShowSurveyModal(true)
                    void addProductIntentForCrossSell({
                        from: ProductKey.ERROR_TRACKING,
                        to: ProductKey.SURVEYS,
                        intent_context: ProductIntentContext.QUICK_SURVEY_STARTED,
                    })
                }}
            >
                <IconMessage />
                Create survey
            </ButtonPrimitive>
            <QuickSurveyModal
                context={{
                    type: QuickSurveyType.ERROR_TRACKING,
                    exceptionType: exceptionType,
                    exceptionMessage: exceptionMessage,
                }}
                info="This survey will trigger when users encounter matching exceptions. Adjust the filters below to target specific errors."
                isOpen={showSurveyModal}
                onCancel={() => setShowSurveyModal(false)}
                showFollowupToggle={true}
            />
        </>
    )
}
