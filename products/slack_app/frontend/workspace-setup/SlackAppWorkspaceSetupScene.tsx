import { useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonBanner, Link, Spinner } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SlackAppWorkspaceSetupDone } from './SlackAppWorkspaceSetupDone'
import { slackAppWorkspaceSetupLogic, SlackAppWorkspaceSetupLogicProps } from './slackAppWorkspaceSetupLogic'
import { SlackAppWorkspaceSetupStep } from './SlackAppWorkspaceSetupStep'

export const scene: SceneExport<SlackAppWorkspaceSetupLogicProps> = {
    component: SlackAppWorkspaceSetupScene,
    logic: slackAppWorkspaceSetupLogic,
    paramsToProps: ({ params: { integrationId } }) => ({ integrationId: Number(integrationId) }),
}

export function SlackAppWorkspaceSetupScene(): JSX.Element {
    const { setup, setupLoading, steps, currentStep, currentStepNumber } = useValues(slackAppWorkspaceSetupLogic)

    return (
        <div className="flex flex-col items-center justify-center min-h-full w-full p-4">
            <div className="flex flex-col items-center gap-4 max-w-160 w-full bg-surface-primary border rounded-lg shadow-sm px-8 py-8">
                {steps.length > 0 ? (
                    <div className="flex items-center gap-3 w-full">
                        <LemonProgress
                            className="flex-1"
                            percent={currentStep ? ((currentStepNumber - 1) / steps.length) * 100 : 100}
                        />
                        <span className="text-xs text-secondary whitespace-nowrap">
                            {currentStep ? `${currentStepNumber} of ${steps.length}` : 'Done'}
                        </span>
                    </div>
                ) : null}

                {setupLoading && !setup ? (
                    <Spinner className="text-2xl" />
                ) : !setup ? (
                    <LemonBanner type="error" className="w-full">
                        We couldn't load the Slack setup. Refresh the page, or go back to PostHog and connect Slack
                        again.
                    </LemonBanner>
                ) : currentStep ? (
                    <SlackAppWorkspaceSetupStep step={currentStep} />
                ) : (
                    <SlackAppWorkspaceSetupDone />
                )}
            </div>

            <Link to={urls.projectHomepage()} className="flex items-center gap-1 mt-6 text-secondary">
                <IconArrowLeft />
                Back to PostHog
            </Link>
        </div>
    )
}
