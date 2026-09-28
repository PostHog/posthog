import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'
import { createElement as mockCreateElement, type ReactNode } from 'react'

import { Link as mockLink } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { EndpointPlayground } from './EndpointPlayground'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useActions: jest.fn(), useValues: jest.fn() }))

jest.mock('@posthog/lemon-ui', () => ({
    LemonButton: ({ children, to }: { children: ReactNode; to?: string }): JSX.Element =>
        to ? mockCreateElement(mockLink, { to }, children) : <button>{children}</button>,
    LemonDivider: (): null => null,
    LemonLabel: ({ children, info }: { children: ReactNode; info?: ReactNode }): JSX.Element => (
        <div>
            {children}
            {info}
        </div>
    ),
    LemonSelect: (): null => null,
    LemonSwitch: (): null => null,
}))

jest.mock('lib/components/CodeSnippet', () => ({
    CodeSnippet: ({ children }: { children: ReactNode }): JSX.Element => <pre>{children}</pre>,
    Language: { Bash: 'bash', JavaScript: 'javascript', Python: 'python' },
}))

jest.mock('lib/components/Superpowers/superpowersLogic', () => ({ superpowersLogic: {} }))
jest.mock('lib/lemon-ui/LemonField', () => ({ LemonField: { Pure: (): null => null } }))
jest.mock('lib/monaco/CodeEditorInline', () => ({ CodeEditorInline: (): null => null }))
jest.mock('~/layout/scenes/components/SceneSection', () => ({
    SceneSection: ({ children }: { children: ReactNode }): JSX.Element => <section>{children}</section>,
}))
jest.mock('../endpointLogic', () => ({ endpointLogic: {} }))
jest.mock('../endpointSceneLogic', () => ({
    endpointSceneLogic: {},
    generateEndpointPayload: (): Record<string, never> => ({}),
}))
jest.mock('scenes/urls', () => ({
    urls: { settings: jest.fn(() => '/settings/environment-secret-api-keys') },
}))

describe('EndpointPlayground', () => {
    const renderPlayground = (activeCodeExampleTab: string): void => {
        ;(useValues as jest.Mock)
            .mockReturnValueOnce({
                endpoint: {
                    name: 'example-endpoint',
                    endpoint_path: '/api/projects/1/endpoints/example-endpoint/run',
                    current_version: 1,
                    is_active: true,
                },
            })
            .mockReturnValueOnce({
                payloadJson: '',
                payloadJsonError: null,
                endpointResult: null,
                endpointResultLoading: false,
                viewingVersion: null,
                debugMode: false,
            })
            .mockReturnValueOnce({ activeCodeExampleTab, selectedCodeExampleVersion: null })
            .mockReturnValueOnce({ superpowersEnabled: false })
        ;(useActions as jest.Mock)
            .mockReturnValueOnce({
                setPayloadJson: jest.fn(),
                setPayloadJsonError: jest.fn(),
                loadEndpointResult: jest.fn(),
                setDebugMode: jest.fn(),
            })
            .mockReturnValueOnce({ setActiveCodeExampleTab: jest.fn(), setSelectedCodeExampleVersion: jest.fn() })

        render(<EndpointPlayground />)
    }

    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
    })

    it('links to project secret API key settings', () => {
        renderPlayground('terminal')

        const apiKeyButton = screen.getByText('Project secret API keys')
        expect(apiKeyButton.closest('a')).toHaveAttribute('href', '/settings/environment-secret-api-keys')
        expect(urls.settings).toHaveBeenCalledWith('environment-secret-api-keys')
        expect(document.body).toHaveTextContent(
            'Create a project secret API key with endpoint:read access and copy a code example to call this endpoint from your application.'
        )
    })

    it.each([
        ['terminal', 'Bearer $POSTHOG_PROJECT_SECRET_API_KEY'],
        ['python', 'f"Bearer {os.environ[\'POSTHOG_PROJECT_SECRET_API_KEY\']}"'],
        ['nodejs', "'Bearer ' + process.env.POSTHOG_PROJECT_SECRET_API_KEY"],
    ])('reads the project secret key from the environment in the %s example', (tab, authorizationHeader) => {
        renderPlayground(tab)

        expect(document.body).toHaveTextContent(authorizationHeader)
    })
})
