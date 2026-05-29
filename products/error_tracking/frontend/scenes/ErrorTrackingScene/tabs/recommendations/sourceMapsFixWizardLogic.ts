import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { Region } from '~/types'

import type { sourceMapsFixWizardLogicType } from './sourceMapsFixWizardLogicType'

export type WizardRating = 'good' | 'bad'

// Delay before we ask "how did the wizard do?" — long enough that the user has
// actually had a chance to copy the command and kick the wizard off.
const FEEDBACK_REVEAL_DELAY_MS = 5000

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
        feedbackText: [
            '',
            {
                openModal: () => '',
                closeModal: () => '',
                dismissFeedback: () => '',
                rateWizard: () => '',
                setFeedbackText: (_, { feedbackText }) => feedbackText,
            },
        ],
        feedbackSubmitted: [
            false,
            {
                openModal: () => false,
                closeModal: () => false,
                dismissFeedback: () => false,
                rateWizard: () => false,
                submitFeedback: () => true,
            },
        ],
    }),

    selectors({
        wizardCommand: [
            () => [preflightLogic.selectors.preflight],
            (preflight): string =>
                `npx -y @posthog/wizard@latest${preflight?.region === Region.EU ? ' --region eu' : ''}`,
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
        rateWizard: ({ rating }) => {
            posthog.capture('source maps wizard rated', { rating, command: values.wizardCommand })
        },
        submitFeedback: () => {
            const feedback = values.feedbackText.trim()
            if (!feedback) {
                return
            }
            posthog.capture('source maps wizard feedback submitted', { rating: values.rating, feedback })
        },
    })),
])
