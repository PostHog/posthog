import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonTextArea, Spinner } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { JourneyStepsEditor } from '../../components/JourneyStepsEditor'
import { MAX_CONVERSION_WINDOW_MINUTES, MIN_CONVERSION_WINDOW_MINUTES } from '../../journeySteps'
import { UserJourneyFormLogicProps, userJourneyFormLogic } from '../../userJourneyFormLogic'

export const scene: SceneExport<UserJourneyFormLogicProps> = {
    component: UserJourneyEditScene,
    logic: userJourneyFormLogic,
    paramsToProps: ({ params: { id } }) => ({ id: id ?? 'new' }),
}

// The scene renders with the route params, and `/user-journeys/new` has no `id` param.
export function UserJourneyEditScene({ id = 'new' }: Partial<UserJourneyFormLogicProps>): JSX.Element {
    const userJourneysEnabled = useFeatureFlag('USER_JOURNEYS')
    const logic = userJourneyFormLogic({ id })
    const { draft, errors, isNew, saving, journeyLoading, journeyLoadError, prefillStepsSkipped } = useValues(logic)
    const { setName, setDescription, setConversionWindow, setStartUrl, submit, loadJourney } = useActions(logic)

    if (!userJourneysEnabled || journeyLoadError === 'not_found') {
        return <NotFound object={userJourneysEnabled ? 'journey' : 'page'} />
    }

    const cancelUrl = isNew ? urls.userJourneys() : urls.userJourney(id)

    return (
        <SceneContent>
            <SceneTitleSection
                name={isNew ? 'New journey' : 'Edit journey'}
                resourceType={{ type: 'insight/paths' }}
                actions={
                    <>
                        <LemonButton type="secondary" size="small" to={cancelUrl} data-attr="user-journey-form-cancel">
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={submit}
                            loading={saving}
                            disabledReason={
                                journeyLoading
                                    ? 'Loading the journey'
                                    : journeyLoadError
                                      ? "Couldn't load the journey"
                                      : undefined
                            }
                            data-attr="user-journey-form-save"
                        >
                            {isNew ? 'Create journey' : 'Save'}
                        </LemonButton>
                    </>
                }
            />

            {journeyLoadError === 'error' ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadJourney, 'data-attr': 'user-journey-form-retry' }}
                >
                    Couldn't load this journey. Check your connection and try again.
                </LemonBanner>
            ) : journeyLoading ? (
                <div className="flex justify-center p-8">
                    <Spinner className="text-2xl" />
                </div>
            ) : (
                <div className="flex flex-col gap-4 max-w-200">
                    {draft.source === 'toolbar' && isNew ? (
                        <LemonBanner type="info">
                            These steps come from the toolbar. Check them, then create the journey.
                        </LemonBanner>
                    ) : null}
                    {prefillStepsSkipped ? (
                        <LemonBanner type="warning">
                            Some steps in the link couldn't be read, so they were left out. Add any missing steps before
                            you create the journey.
                        </LemonBanner>
                    ) : null}
                    <LemonField.Pure label="Name" error={errors.name}>
                        <LemonInput
                            value={draft.name}
                            onChange={setName}
                            placeholder="Sign up from pricing"
                            autoFocus={isNew && !draft.name}
                            data-attr="user-journey-name"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Description" showOptional error={errors.description}>
                        <LemonTextArea
                            value={draft.description}
                            onChange={setDescription}
                            placeholder="What this journey covers and why it matters"
                            minRows={2}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure
                        label="Conversion window"
                        error={errors.conversion_window_minutes}
                        help="How long a session has to go from the first step to the last."
                    >
                        <LemonInput
                            type="number"
                            className="max-w-50"
                            min={MIN_CONVERSION_WINDOW_MINUTES}
                            max={MAX_CONVERSION_WINDOW_MINUTES}
                            value={draft.conversion_window_minutes}
                            onChange={(value) => setConversionWindow(value ?? undefined)}
                            suffix={<span className="text-secondary">minutes</span>}
                            data-attr="user-journey-conversion-window"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure
                        label="Start URL"
                        showOptional
                        error={errors.start_url}
                        help='The page a run opens before the first step. Leave it empty if the first step is a pageview set to "URL is" with a full address, like https://example.com/pricing.'
                    >
                        <LemonInput
                            value={draft.start_url}
                            onChange={setStartUrl}
                            placeholder="https://example.com/pricing"
                            data-attr="user-journey-start-url"
                        />
                    </LemonField.Pure>
                    <JourneyStepsEditor id={id} />
                </div>
            )}
        </SceneContent>
    )
}
