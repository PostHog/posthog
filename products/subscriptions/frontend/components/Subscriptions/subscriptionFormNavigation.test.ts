import { SubscriptionResourceTypes } from '~/types'

import type { ProactiveConfigurationOptionsApi } from 'products/subscriptions/frontend/generated/api.schemas'

import {
    getSubscriptionEditTabs,
    getSubscriptionWizardSteps,
    normalizeSubscriptionEditTab,
    normalizeSubscriptionWizardStep,
    shouldWaitForSubscriptionActions,
    shouldShowSubscriptionActions,
    subscriptionEditTabForErrors,
    subscriptionWizardStepForErrors,
} from './subscriptionFormNavigation'
import type { SubscriptionFormType } from './subscriptionLogic'

const UNCONFIGURED_SUBSCRIPTION = {
    resource_type: SubscriptionResourceTypes.AiPrompt,
    proactive_config: {
        enabled: false,
        create_draft_pr: false,
        repository: null,
        repository_integration_id: null,
        repository_grant_id: null,
        public_research_subject_id: null,
    },
} as SubscriptionFormType

const AVAILABLE_OPTIONS = {
    proactive_available: true,
    draft_pr_available: true,
    repositories: [],
    public_research_subjects: [],
} as ProactiveConfigurationOptionsApi

describe('subscriptionFormNavigation', () => {
    it.each([
        ['non-AI while loading', SubscriptionResourceTypes.Insight, null, true, false, false],
        ['AI while loading', SubscriptionResourceTypes.AiPrompt, null, true, false, false],
        ['AI after a load failure', SubscriptionResourceTypes.AiPrompt, null, false, true, true],
        ['AI when available', SubscriptionResourceTypes.AiPrompt, AVAILABLE_OPTIONS, false, false, true],
        [
            'AI when unavailable',
            SubscriptionResourceTypes.AiPrompt,
            { ...AVAILABLE_OPTIONS, proactive_available: false },
            false,
            false,
            false,
        ],
    ])('derives Actions visibility for %s', (_label, resourceType, options, loading, failed, expected) => {
        expect(
            shouldShowSubscriptionActions({
                subscription: { ...UNCONFIGURED_SUBSCRIPTION, resource_type: resourceType },
                proactiveConfigurationOptions: options,
                proactiveConfigurationOptionsLoading: loading,
                proactiveConfigurationOptionsLoadFailed: failed,
            })
        ).toBe(expected)
    })

    it('waits before rendering AI navigation until initial Actions availability resolves', () => {
        expect(
            shouldWaitForSubscriptionActions({
                subscription: UNCONFIGURED_SUBSCRIPTION,
                proactiveConfigurationOptions: null,
                proactiveConfigurationOptionsLoading: true,
                proactiveConfigurationOptionsLoadFailed: false,
            })
        ).toBe(true)
        expect(
            shouldWaitForSubscriptionActions({
                subscription: UNCONFIGURED_SUBSCRIPTION,
                proactiveConfigurationOptions: null,
                proactiveConfigurationOptionsLoading: false,
                proactiveConfigurationOptionsLoadFailed: true,
            })
        ).toBe(false)
    })

    it('keeps Actions visible for saved configuration while Pulse is unavailable', () => {
        expect(
            shouldShowSubscriptionActions({
                subscription: {
                    ...UNCONFIGURED_SUBSCRIPTION,
                    proactive_config: {
                        ...UNCONFIGURED_SUBSCRIPTION.proactive_config,
                        enabled: true,
                        create_draft_pr: true,
                        repository: 'example/product',
                        repository_integration_id: 17,
                    },
                },
                proactiveConfigurationOptions: { ...AVAILABLE_OPTIONS, proactive_available: false },
                proactiveConfigurationOptionsLoading: false,
                proactiveConfigurationOptionsLoadFailed: false,
            })
        ).toBe(true)
    })

    it('omits Actions from create and edit navigation when it is unavailable', () => {
        expect(getSubscriptionWizardSteps(false).map(({ key }) => key)).toEqual([
            'report',
            'notify',
            'schedule',
            'review',
        ])
        expect(getSubscriptionEditTabs(false).map(({ key }) => key)).toEqual(['content', 'delivery', 'settings'])
    })

    it('falls forward in creation and back to Content in editing when Actions disappears', () => {
        expect(normalizeSubscriptionWizardStep('actions', false)).toBe('notify')
        expect(normalizeSubscriptionEditTab('actions', false)).toBe('content')
    })

    it('routes hidden validation errors to their first relevant section', () => {
        expect(subscriptionWizardStepForErrors({ proactive_config: { repository: 'Select a repository' } }, true)).toBe(
            'actions'
        )
        expect(subscriptionWizardStepForErrors({ target_value: 'Choose a recipient' }, true)).toBe('notify')
        expect(subscriptionEditTabForErrors({ start_date: 'Choose a time' }, true)).toBe('delivery')
        expect(subscriptionEditTabForErrors({ prompt: 'Enter a prompt' }, true)).toBe('content')
    })
})
