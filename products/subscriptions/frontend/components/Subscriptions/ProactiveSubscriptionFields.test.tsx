import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { ProactiveSubscriptionFields } from './ProactiveSubscriptionFields'
import type { SubscriptionFormType } from './subscriptionLogic'

jest.mock('kea', () => ({
    useActions: jest.fn(),
    useValues: jest.fn(),
}))

jest.mock('./subscriptionLogic', () => ({
    subscriptionLogic: jest.fn(() => ({})),
}))

jest.mock('@posthog/lemon-ui', () => ({
    Link: ({ children }: { children: ReactNode }) => <span>{children}</span>,
}))

jest.mock('lib/lemon-ui/LemonBanner', () => ({
    LemonBanner: ({
        children,
        action,
    }: {
        children: ReactNode
        action?: { children: ReactNode; onClick: () => void; disabled?: boolean; loading?: boolean }
    }) => (
        <div>
            {children}
            {action ? (
                <button disabled={action.disabled ?? action.loading} onClick={action.onClick}>
                    {action.children}
                </button>
            ) : null}
        </div>
    ),
}))

jest.mock('lib/lemon-ui/LemonField', () => ({
    LemonField: ({ label, help, children }: { label?: ReactNode; help?: ReactNode; children?: ReactNode }) => (
        <div>
            {label}
            {help}
            {children}
        </div>
    ),
}))

jest.mock('lib/lemon-ui/LemonInputSelect/LemonInputSelect', () => ({
    LemonInputSelect: ({ options }: { options: { key: string; label: string }[] }) => (
        <div>{options.map((option) => option.label).join(', ')}</div>
    ),
}))

jest.mock('lib/lemon-ui/LemonSelect', () => ({
    LemonSelect: ({ options }: { options: { label: string }[] }) => (
        <div>{options.map((option) => option.label).join(', ')}</div>
    ),
}))

jest.mock('lib/lemon-ui/LemonSkeleton', () => ({
    LemonSkeleton: () => <div>Loading</div>,
}))

jest.mock('lib/lemon-ui/LemonSwitch', () => ({
    LemonSwitch: ({ label }: { label: ReactNode }) => <div>{label}</div>,
}))

jest.mock('scenes/urls', () => ({
    urls: { settings: () => '/settings/user-personal-integrations' },
}))

const mockedUseValues = useValues as jest.Mock
const mockedUseActions = useActions as jest.Mock
const logicProps = { id: 'new' as const }

function subscription(proactiveConfig: SubscriptionFormType['proactive_config']): SubscriptionFormType {
    return { proactive_config: proactiveConfig } as SubscriptionFormType
}

describe('ProactiveSubscriptionFields', () => {
    afterEach(cleanup)

    beforeEach(() => {
        mockedUseActions.mockReturnValue({
            loadProactiveConfigurationOptions: jest.fn(),
            selectProactiveRepository: jest.fn(),
            setDraftPrEnabled: jest.fn(),
            setProactiveEnabled: jest.fn(),
            setPublicResearchSubject: jest.fn(),
        })
    })

    it('stays hidden for new configuration while the server control is off', () => {
        mockedUseValues.mockReturnValue({
            proactiveConfigurationOptions: {
                proactive_available: false,
                draft_pr_available: false,
                repositories: [],
                public_research_subjects: [],
            },
            proactiveConfigurationOptionsLoading: false,
        })

        const { container } = render(
            <ProactiveSubscriptionFields
                logicProps={logicProps}
                subscription={subscription({
                    enabled: false,
                    repository: null,
                    repository_integration_id: null,
                    create_draft_pr: false,
                    repository_grant_id: null,
                    public_research_subject_id: null,
                })}
            />
        )

        expect(container).toBeEmptyDOMElement()
    })

    it('explains standing consent and only lists server-authorized repository options', () => {
        mockedUseValues.mockReturnValue({
            proactiveConfigurationOptions: {
                proactive_available: true,
                draft_pr_available: true,
                repositories: [{ repository: 'example/product', repository_integration_id: 17 }],
                public_research_subjects: [
                    {
                        id: '00000000-0000-4000-8000-000000000010',
                        display_name: 'Example public docs',
                        canonical_domain: 'example.com',
                    },
                ],
            },
            proactiveConfigurationOptionsLoading: false,
        })

        render(
            <ProactiveSubscriptionFields
                logicProps={logicProps}
                subscription={subscription({
                    enabled: true,
                    repository: 'example/product',
                    repository_integration_id: 17,
                    create_draft_pr: true,
                    repository_grant_id: null,
                    public_research_subject_id: null,
                })}
            />
        )

        expect(screen.getByText('Act on useful findings from future reports')).toBeInTheDocument()
        expect(screen.getByText('Automatically open one draft pull request')).toBeInTheDocument()
        expect(screen.getByText('example/product')).toBeInTheDocument()
        expect(screen.getByText(/Example public docs \(example.com\)/)).toBeInTheDocument()
        expect(screen.getByText(/never starts an experiment or sends traffic automatically/i)).toBeInTheDocument()
    })

    it('hides new draft pull request configuration while its server control is off', () => {
        mockedUseValues.mockReturnValue({
            proactiveConfigurationOptions: {
                proactive_available: true,
                draft_pr_available: false,
                repositories: [],
                public_research_subjects: [],
            },
            proactiveConfigurationOptionsLoading: false,
        })

        render(
            <ProactiveSubscriptionFields
                logicProps={logicProps}
                subscription={subscription({
                    enabled: true,
                    repository: null,
                    repository_integration_id: null,
                    create_draft_pr: false,
                    repository_grant_id: null,
                    public_research_subject_id: null,
                })}
            />
        )

        expect(screen.queryByText('Automatically open one draft pull request')).not.toBeInTheDocument()
        expect(screen.queryByPlaceholderText('Select a repository')).not.toBeInTheDocument()
    })

    it('keeps an existing configuration visible so it can be turned off', () => {
        mockedUseValues.mockReturnValue({
            proactiveConfigurationOptions: {
                proactive_available: false,
                draft_pr_available: false,
                repositories: [],
                public_research_subjects: [],
            },
            proactiveConfigurationOptionsLoading: false,
        })

        render(
            <ProactiveSubscriptionFields
                logicProps={{ id: 42 }}
                subscription={subscription({
                    enabled: true,
                    repository: null,
                    repository_integration_id: null,
                    create_draft_pr: false,
                    repository_grant_id: null,
                    public_research_subject_id: null,
                })}
            />
        )

        expect(screen.getByText(/Proactive follow-up is currently unavailable/)).toBeInTheDocument()
        expect(screen.getByText('Act on useful findings from future reports')).toBeInTheDocument()
    })

    it('shows a retry when proactive configuration options fail to load', () => {
        const loadProactiveConfigurationOptions = jest.fn()
        mockedUseActions.mockReturnValue({
            loadProactiveConfigurationOptions,
            selectProactiveRepository: jest.fn(),
            setDraftPrEnabled: jest.fn(),
            setProactiveEnabled: jest.fn(),
            setPublicResearchSubject: jest.fn(),
        })
        mockedUseValues.mockReturnValue({
            proactiveConfigurationOptions: null,
            proactiveConfigurationOptionsLoading: false,
            proactiveConfigurationOptionsLoadFailed: true,
        })

        render(
            <ProactiveSubscriptionFields
                logicProps={logicProps}
                subscription={subscription({
                    enabled: false,
                    repository: null,
                    repository_integration_id: null,
                    create_draft_pr: false,
                    repository_grant_id: null,
                    public_research_subject_id: null,
                })}
            />
        )

        expect(screen.getByText('Could not load proactive configuration options.')).toBeInTheDocument()
        fireEvent.click(screen.getByText('Retry'))
        expect(loadProactiveConfigurationOptions).toHaveBeenCalledTimes(1)
    })

    it('disables retry while proactive configuration options are loading', () => {
        const loadProactiveConfigurationOptions = jest.fn()
        mockedUseActions.mockReturnValue({
            loadProactiveConfigurationOptions,
            selectProactiveRepository: jest.fn(),
            setDraftPrEnabled: jest.fn(),
            setProactiveEnabled: jest.fn(),
            setPublicResearchSubject: jest.fn(),
        })
        mockedUseValues.mockReturnValue({
            proactiveConfigurationOptions: null,
            proactiveConfigurationOptionsLoading: true,
            proactiveConfigurationOptionsLoadFailed: true,
        })

        render(
            <ProactiveSubscriptionFields
                logicProps={logicProps}
                subscription={subscription({
                    enabled: true,
                    repository: null,
                    repository_integration_id: null,
                    create_draft_pr: false,
                    repository_grant_id: null,
                    public_research_subject_id: null,
                })}
            />
        )

        const retry = screen.getByText('Retry').closest('button')
        expect(retry).not.toBeNull()
        expect(retry).toBeDisabled()
        fireEvent.click(retry!)
        expect(loadProactiveConfigurationOptions).not.toHaveBeenCalled()
    })
})
