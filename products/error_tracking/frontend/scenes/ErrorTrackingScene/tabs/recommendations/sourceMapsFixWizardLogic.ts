import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { getSurveyIdBasedResponseKey, getSurveyResponseKey } from 'scenes/surveys/utils'

import { Region, SurveyEventName, SurveyEventProperties } from '~/types'

import type { sourceMapsFixWizardLogicType } from './sourceMapsFixWizardLogicType'

export type WizardRating = 'good' | 'bad'

// Delay before we ask "how did the wizard do?" — long enough that the user has
// actually had a chance to copy the command and kick the wizard off.
const FEEDBACK_REVEAL_DELAY_MS = 1000

export const RATING_SCALE = 5
const GOOD_RATING = 5
const BAD_RATING = 1

// API survey that collects source maps wizard feedback: a 1-5 rating question
// followed by an open feedback question.
const SURVEY_ID = '019e7d83-63e0-0000-8d8d-a7d09a0cd405'
const RATING_QUESTION_ID = '999be3e0-8017-4357-9e83-ef313fac1d50'
const FEEDBACK_QUESTION_ID = 'b0d02cd2-7144-4041-bdf4-9f9867a23e65'

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
        openModal: true,
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
                `npx -y @posthog/wizard@latest upload-sourcemaps${preflight?.region === Region.EU ? ' --region eu' : ''}`,
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        openModal: () => {
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
