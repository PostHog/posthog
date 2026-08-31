import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { preflightLogic } from 'lib/logic/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'

import { SubscriptionResourceTypes } from '~/types'

import type { SubscriptionFormType } from './subscriptionLogic'
import { SubscriptionWizard } from './SubscriptionWizard'

const mockLogic = { path: ['subscription-wizard-test'] }
const setSubscriptionWizardStep = jest.fn()

jest.mock('kea', () => ({
    useActions: jest.fn(),
    useValues: jest.fn(),
}))

jest.mock('kea-forms', () => ({
    Form: ({ children }: { children: ReactNode }) => <form>{children}</form>,
}))

jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: () => true,
}))

jest.mock('./subscriptionLogic', () => ({
    subscriptionLogic: jest.fn(() => mockLogic),
}))

jest.mock('./SubscriptionReportSection', () => ({
    SubscriptionReportSection: () => <div>Report fields</div>,
}))

jest.mock('./SubscriptionNotifySection', () => ({
    SubscriptionNotifySection: () => <div>Notify fields</div>,
}))

jest.mock('./SubscriptionScheduleSection', () => ({
    SubscriptionScheduleSection: () => <div>Schedule fields</div>,
}))

jest.mock('./SubscriptionSettingsSection', () => ({
    SubscriptionSettingsSection: () => <div>Settings fields</div>,
}))

jest.mock('./ProactiveSubscriptionFields', () => ({
    ProactiveSubscriptionFields: () => <div>Actions fields</div>,
}))

jest.mock('./views/EditSubscription', () => ({
    SubscriptionCreationGate: ({ children }: { children: ReactNode }) => <>{children}</>,
    SubscriptionFormSkeleton: () => <div>Subscription form loading</div>,
}))

const mockedUseValues = useValues as jest.Mock
const mockedUseActions = useActions as jest.Mock

function subscription(
    resourceType: SubscriptionFormType['resource_type'],
    proactiveEnabled = false
): SubscriptionFormType {
    return {
        resource_type: resourceType,
        title: 'Weekly report',
        prompt: resourceType === SubscriptionResourceTypes.AiPrompt ? 'Find activation opportunities' : undefined,
        target_type: 'email',
        target_value: 'owner@example.com',
        frequency: 'weekly',
        interval: 1,
        start_date: '2026-08-31T09:00:00Z',
        byweekday: ['monday'],
        dashboard_export_insights: [],
        contexts: [],
        proactive_config: {
            enabled: proactiveEnabled,
            create_draft_pr: proactiveEnabled,
            repository: proactiveEnabled ? 'PostHog/posthog' : null,
            repository_integration_id: proactiveEnabled ? 17 : null,
            repository_grant_id: null,
            public_research_subject_id: null,
        },
    } as unknown as SubscriptionFormType
}

function renderWizard({
    resourceType = SubscriptionResourceTypes.Insight,
    currentStep = 'notify',
    proactiveAvailable = false,
    proactiveLoading = false,
    proactiveFailed = false,
    proactiveEnabled = false,
}: {
    resourceType?: SubscriptionFormType['resource_type']
    currentStep?: 'report' | 'actions' | 'notify' | 'schedule' | 'review'
    proactiveAvailable?: boolean
    proactiveLoading?: boolean
    proactiveFailed?: boolean
    proactiveEnabled?: boolean
} = {}): void {
    mockedUseValues.mockImplementation((logic) => {
        if (logic === mockLogic) {
            return {
                subscription: subscription(resourceType, proactiveEnabled),
                subscriptionLoading: false,
                subscriptionInitialized: true,
                isSubscriptionSubmitting: false,
                subscriptionChanged: true,
                subscriptionWizardStep: currentStep,
                proactiveConfigurationOptions: proactiveLoading
                    ? null
                    : {
                          proactive_available: proactiveAvailable,
                          draft_pr_available: proactiveAvailable,
                          repositories: [],
                          public_research_subjects: [],
                      },
                proactiveConfigurationOptionsLoading: proactiveLoading,
                proactiveConfigurationOptionsLoadFailed: proactiveFailed,
            }
        }
        if (logic === preflightLogic) {
            return { preflight: { cloud: true, email_service_available: true } }
        }
        if (logic === organizationLogic) {
            return { currentOrganization: { is_ai_data_processing_approved: true } }
        }
        return {}
    })
    mockedUseActions.mockReturnValue({
        generatePreview: jest.fn(),
        resetSubscription: jest.fn(),
        setSubscriptionWizardStep,
    })
    render(<SubscriptionWizard insightName="Activation" onCancel={jest.fn()} />)
}

describe('SubscriptionWizard', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    afterEach(cleanup)

    it('omits Actions for snapshots and keeps the narrow tab bar keyboard accessible', () => {
        renderWizard()

        expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
            '1. Report',
            '2. Notify',
            '3. Schedule',
            '4. Review',
        ])
        expect(screen.getByRole('tablist').parentElement).toHaveClass('min-w-0')
        fireEvent.keyDown(screen.getByText('1. Report'), { key: 'Enter' })
        expect(setSubscriptionWizardStep).toHaveBeenCalledWith('report')
    })

    it('shows Actions for an AI report only after availability resolves', () => {
        renderWizard({
            resourceType: SubscriptionResourceTypes.AiPrompt,
            currentStep: 'report',
            proactiveAvailable: true,
        })

        expect(screen.getByText('2. Actions')).toBeInTheDocument()
    })

    it('keeps AI navigation on the loading state while Actions availability is unresolved', () => {
        renderWizard({
            resourceType: SubscriptionResourceTypes.AiPrompt,
            currentStep: 'report',
            proactiveLoading: true,
        })

        expect(screen.getByText('Subscription form loading')).toBeInTheDocument()
        expect(screen.queryByRole('tablist')).not.toBeInTheDocument()
    })

    it('summarizes approved follow-up actions on Review', () => {
        renderWizard({
            resourceType: SubscriptionResourceTypes.AiPrompt,
            currentStep: 'review',
            proactiveAvailable: true,
            proactiveEnabled: true,
        })

        expect(screen.getByText('Goal')).toBeInTheDocument()
        expect(screen.getByText('Recommendations, draft pull request, and experiment draft')).toBeInTheDocument()
    })
})
