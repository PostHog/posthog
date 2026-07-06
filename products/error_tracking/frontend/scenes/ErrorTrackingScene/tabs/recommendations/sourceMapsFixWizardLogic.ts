import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { getSurveyIdBasedResponseKey, getSurveyResponseKey } from 'scenes/surveys/utils'

import { Region, SurveyEventName, SurveyEventProperties } from '~/types'

import type { sourceMapsFixWizardLogicType } from './sourceMapsFixWizardLogicType'

export type WizardRating = 'good' | 'bad'
export type WizardOpenSource = 'issues_list' | 'recommendations'

export const SOURCE_MAPS_DOCS_URL = 'https://posthog.com/docs/error-tracking/upload-source-maps'

// Delay before we ask "how did the wizard do?" — long enough that the user has
// actually had a chance to copy the command and kick the wizard off.
const FEEDBACK_REVEAL_DELAY_MS = 1000

export const RATING_SCALE = 5
const GOOD_RATING = 5
const BAD_RATING = 1

// API survey that collects source maps wizard feedback: a 1-5 rating question
// followed by an open feedback question.
const SURVEY_ID = '019e7335-af36-0000-42a8-ad5add623630'
const RATING_QUESTION_ID = '030dde7d-0dee-4d79-b568-ed16e85b431c'
const FEEDBACK_QUESTION_ID = '03e1255c-6daf-46a2-9629-2354bcd230ff'

export const sourceMapsFixWizardLogic = kea<sourceMapsFixWizardLogicType>([
    path([
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingScene',
        'tabs',
        'recommendations',
        'sourceMapsFixWizardLogic',
    ]),

    actions({
        openModal: (source: WizardOpenSource) => ({ source }),
        closeModal: true,
        revealFeedback: true,
        rateWizard: (rating: WizardRating) => ({ rating }),
        setRatingScore: (ratingScore: number) => ({ ratingScore }),
        setFeedbackText: (feedbackText: string) => ({ feedbackText }),
        submitFeedback: true,
        dismissFeedback: true,
    }),

    reducers({
        isModalOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],
        feedbackRevealed: [
            false,
            {
                openModal: () => false,
                closeModal: () => false,
                revealFeedback: () => true,
            },
        ],
        rating: [
            null as WizardRating | null,
            {
                openModal: () => null,
                closeModal: () => null,
                dismissFeedback: () => null,
                rateWizard: (_, { rating }) => rating,
            },
        ],
        // Not reset on dismissFeedback: the popover stays mounted during its
        // fade-out, so clearing these here would flash the content back to the
        // input form mid-transition. rateWizard/openModal/closeModal reset them.
        ratingScore: [
            null as number | null,
            {
                openModal: () => null,
                closeModal: () => null,
                rateWizard: (_, { rating }) => (rating === 'good' ? GOOD_RATING : BAD_RATING),
                setRatingScore: (_, { ratingScore }) => ratingScore,
            },
        ],
        feedbackText: [
            '',
            {
                openModal: () => '',
                closeModal: () => '',
                rateWizard: () => '',
                setFeedbackText: (_, { feedbackText }) => feedbackText,
            },
        ],
        feedbackSubmitted: [
            false,
            {
                openModal: () => false,
                closeModal: () => false,
                rateWizard: () => false,
                submitFeedback: () => true,
            },
        ],
    }),

    selectors({
        wizardCommand: [
            () => [preflightLogic.selectors.preflight],
            (preflight): string =>
                `npx -y @posthog/wizard@latest upload-source-maps${preflight?.region === Region.EU ? ' --region eu' : ''}`,
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        openModal: ({ source }) => {
            posthog.capture('error_tracking_source_maps_wizard_opened', { source })
            cache.disposables.dispose('feedback-reveal')
            cache.disposables.add(() => {
                const timeout = setTimeout(() => actions.revealFeedback(), FEEDBACK_REVEAL_DELAY_MS)
                return () => clearTimeout(timeout)
            }, 'feedback-reveal')
        },
        closeModal: () => {
            cache.disposables.dispose('feedback-reveal')
        },
        submitFeedback: () => {
            const feedback = values.feedbackText.trim()
            posthog.capture(SurveyEventName.SENT, {
                [SurveyEventProperties.SURVEY_ID]: SURVEY_ID,
                [getSurveyResponseKey(0)]: values.ratingScore,
                [getSurveyIdBasedResponseKey(RATING_QUESTION_ID)]: values.ratingScore,
                [getSurveyResponseKey(1)]: feedback,
                [getSurveyIdBasedResponseKey(FEEDBACK_QUESTION_ID)]: feedback,
                [SurveyEventProperties.SURVEY_COMPLETED]: true,
            })
        },
    })),
])
