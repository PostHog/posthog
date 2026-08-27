import { useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { SURVEY_CREATED_SOURCE } from 'scenes/surveys/constants'
import { surveysLogic } from 'scenes/surveys/surveysLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

/**
 * The surveys empty state's actions: the same survey wizard the scene's "New
 * survey" button opens, plus the Max-driven creation flow the old empty state
 * offered.
 */
export function NewSurveyActions(): JSX.Element {
    const { isMaxAvailable } = useValues(maxGlobalLogic)
    const { openMax } = useMaxTool({
        identifier: 'create_survey',
        initialMaxPrompt: 'Create a survey to collect ',
        callback: (toolOutput) => {
            surveysLogic
                .findMounted()
                ?.actions.handleMaxSurveyCreated(toolOutput, SURVEY_CREATED_SOURCE.SURVEY_EMPTY_STATE)
        },
        // `openMax` is null only when the tool is inactive, so without this the button stays
        // enabled on an instance without PostHog AI and opens a panel saying it isn't set up.
        active: isMaxAvailable,
    })

    return (
        <div className="flex items-center gap-2">
            <AccessControlAction
                resourceType={AccessControlResourceType.Survey}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonButton
                    type="primary"
                    to={urls.surveyWizard()}
                    data-attr="new-survey"
                    onClick={() => {
                        teamLogic.findMounted()?.actions.addProductIntent({
                            product_type: ProductKey.SURVEYS,
                            intent_context: ProductIntentContext.SURVEY_ADD_NEW,
                        })
                    }}
                >
                    Create your first survey
                </LemonButton>
            </AccessControlAction>
            {isMaxAvailable ? (
                <LemonButton
                    type="secondary"
                    icon={<IconSparkles />}
                    data-attr="surveys-empty-state-create-with-ai"
                    onClick={() => openMax?.()}
                    disabledReason={openMax ? undefined : 'PostHog AI is unavailable here'}
                >
                    Create with AI
                </LemonButton>
            ) : null}
        </div>
    )
}
