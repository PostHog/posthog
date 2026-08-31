import { SubscriptionResourceTypes } from '~/types'

import type { ProactiveConfigurationOptionsApi } from 'products/subscriptions/frontend/generated/api.schemas'

import type { SubscriptionFormType } from './subscriptionLogic'

export type SubscriptionWizardStep = 'report' | 'actions' | 'notify' | 'schedule' | 'review'
export type SubscriptionEditTab = 'content' | 'actions' | 'delivery' | 'settings'

export interface SubscriptionNavigationItem<T extends string> {
    key: T
    label: string
    description: string
}

const WIZARD_STEPS: readonly SubscriptionNavigationItem<SubscriptionWizardStep>[] = [
    { key: 'report', label: 'Report', description: 'Choose what the report should cover.' },
    { key: 'actions', label: 'Actions', description: 'Choose what PostHog can prepare from useful findings.' },
    { key: 'notify', label: 'Notify', description: 'Choose where to send the report.' },
    { key: 'schedule', label: 'Schedule', description: 'Choose when to run the report.' },
    { key: 'review', label: 'Review', description: 'Check the details before creating the subscription.' },
]

const EDIT_TABS: readonly SubscriptionNavigationItem<SubscriptionEditTab>[] = [
    { key: 'content', label: 'Content', description: 'What this subscription reports.' },
    { key: 'actions', label: 'Actions', description: 'What PostHog can prepare from useful findings.' },
    { key: 'delivery', label: 'Delivery', description: 'Where and when this subscription runs.' },
    { key: 'settings', label: 'Settings', description: 'Subscription status and optional delivery settings.' },
]

interface SubscriptionActionsVisibilityInput {
    subscription: SubscriptionFormType
    proactiveConfigurationOptions: ProactiveConfigurationOptionsApi | null
    proactiveConfigurationOptionsLoading: boolean
    proactiveConfigurationOptionsLoadFailed: boolean
}

function hasSavedSubscriptionActions(subscription: SubscriptionFormType): boolean {
    const config = subscription.proactive_config
    return Boolean(
        config?.enabled ||
        config?.create_draft_pr ||
        config?.repository ||
        config?.repository_integration_id ||
        config?.public_research_subject_id
    )
}

export function shouldWaitForSubscriptionActions({
    subscription,
    proactiveConfigurationOptions,
    proactiveConfigurationOptionsLoading,
}: SubscriptionActionsVisibilityInput): boolean {
    return Boolean(
        subscription.resource_type === SubscriptionResourceTypes.AiPrompt &&
        !hasSavedSubscriptionActions(subscription) &&
        !proactiveConfigurationOptions &&
        proactiveConfigurationOptionsLoading
    )
}

export function shouldShowSubscriptionActions({
    subscription,
    proactiveConfigurationOptions,
    proactiveConfigurationOptionsLoadFailed,
}: SubscriptionActionsVisibilityInput): boolean {
    if (subscription.resource_type !== SubscriptionResourceTypes.AiPrompt) {
        return false
    }
    if (hasSavedSubscriptionActions(subscription)) {
        return true
    }
    if (proactiveConfigurationOptionsLoadFailed) {
        return true
    }
    return proactiveConfigurationOptions?.proactive_available === true
}

export function getSubscriptionWizardSteps(
    showActions: boolean
): readonly SubscriptionNavigationItem<SubscriptionWizardStep>[] {
    return showActions ? WIZARD_STEPS : WIZARD_STEPS.filter(({ key }) => key !== 'actions')
}

export function getSubscriptionEditTabs(
    showActions: boolean
): readonly SubscriptionNavigationItem<SubscriptionEditTab>[] {
    return showActions ? EDIT_TABS : EDIT_TABS.filter(({ key }) => key !== 'actions')
}

export function normalizeSubscriptionWizardStep(
    activeStep: SubscriptionWizardStep,
    showActions: boolean
): SubscriptionWizardStep {
    return activeStep === 'actions' && !showActions ? 'notify' : activeStep
}

export function normalizeSubscriptionEditTab(
    activeTab: SubscriptionEditTab,
    showActions: boolean
): SubscriptionEditTab {
    return activeTab === 'actions' && !showActions ? 'content' : activeTab
}

type SubscriptionFormErrors = Record<string, unknown> | undefined

function hasError(errors: SubscriptionFormErrors, keys: string[]): boolean {
    return keys.some((key) => Boolean(errors?.[key]))
}

export function subscriptionWizardStepForErrors(
    errors: SubscriptionFormErrors,
    showActions: boolean
): Exclude<SubscriptionWizardStep, 'review'> | null {
    if (hasError(errors, ['title', 'prompt', 'ai_prompt_config', 'dashboard_export_insights'])) {
        return 'report'
    }
    if (showActions && hasError(errors, ['proactive_config'])) {
        return 'actions'
    }
    if (hasError(errors, ['target_type', 'target_value', 'integration_id'])) {
        return 'notify'
    }
    if (hasError(errors, ['frequency', 'interval', 'start_date', 'byweekday', 'bysetpos'])) {
        return 'schedule'
    }
    return null
}

export function subscriptionEditTabForErrors(
    errors: SubscriptionFormErrors,
    showActions: boolean
): SubscriptionEditTab | null {
    const wizardStep = subscriptionWizardStepForErrors(errors, showActions)
    if (wizardStep === 'report') {
        return 'content'
    }
    if (wizardStep === 'actions') {
        return 'actions'
    }
    if (wizardStep === 'notify' || wizardStep === 'schedule') {
        return 'delivery'
    }
    return null
}
