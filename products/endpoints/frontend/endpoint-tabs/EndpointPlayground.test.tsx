import { urls } from 'scenes/urls'

import type { EndpointVersionType } from '~/types'

import { generateEndpointPayload } from '../endpointSceneLogic'
import {
    generateNodeExample,
    generatePythonExample,
    generateTerminalExample,
    PROJECT_SECRET_API_KEY_SETTINGS_SECTION,
} from './EndpointPlayground'

jest.mock('../endpointLogic', () => ({ endpointLogic: {} }))
jest.mock('../endpointSceneLogic', () => ({ generateEndpointPayload: jest.fn() }))

describe('EndpointPlayground code examples', () => {
    const endpoint = {
        endpoint_path: '/api/projects/1/endpoints/example-endpoint/run',
        current_version: 1,
    } as EndpointVersionType
    const mockGenerateEndpointPayload = generateEndpointPayload as jest.MockedFunction<typeof generateEndpointPayload>

    afterEach(() => {
        jest.clearAllMocks()
    })

    it('links to project secret API key settings', () => {
        expect(urls.settings(PROJECT_SECRET_API_KEY_SETTINGS_SECTION)).toBe('/settings/environment-secret-api-keys')
    })

    it.each([
        ['terminal', generateTerminalExample, 'Bearer $POSTHOG_PROJECT_SECRET_API_KEY', "-d '{"],
        ['Python', generatePythonExample, "os.environ['POSTHOG_PROJECT_SECRET_API_KEY']", 'data=json.dumps(payload)'],
        ['Node.js', generateNodeExample, 'process.env.POSTHOG_PROJECT_SECRET_API_KEY', 'body: JSON.stringify(payload)'],
    ])(
        'uses an environment API key and request payload in the %s example',
        (_language, generateExample, environmentAccessExpression, payloadExpression) => {
            mockGenerateEndpointPayload.mockReturnValue({ variables: { limit: 10 } })

            const example = generateExample(endpoint, null)

            expect(example).toContain(environmentAccessExpression)
            expect(example).toContain(payloadExpression)
        }
    )

    it.each([
        ['terminal', generateTerminalExample, 'Bearer $POSTHOG_PROJECT_SECRET_API_KEY', "-d '{"],
        ['Python', generatePythonExample, "os.environ['POSTHOG_PROJECT_SECRET_API_KEY']", 'data=json.dumps(payload)'],
        ['Node.js', generateNodeExample, 'process.env.POSTHOG_PROJECT_SECRET_API_KEY', 'body: JSON.stringify(payload)'],
    ])(
        'uses an environment API key without a request payload in the %s example',
        (_language, generateExample, environmentAccessExpression, payloadExpression) => {
            mockGenerateEndpointPayload.mockReturnValue({})

            const example = generateExample(endpoint, null)

            expect(example).toContain(environmentAccessExpression)
            expect(example).not.toContain(payloadExpression)
        }
    )
})
