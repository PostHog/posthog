import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { personalAPIKeysLogic } from 'scenes/settings/user/personalAPIKeysLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { metricsPrometheusConnectLogic } from './metricsPrometheusConnectLogic'

describe('metricsPrometheusConnectLogic', () => {
    let logic: ReturnType<typeof metricsPrometheusConnectLogic.build>
    let captureSpy: jest.SpyInstance

    beforeEach(() => {
        useMocks({ get: { '/api/organizations/@current/projects/': { results: [] } } })
        initKeaTests()
        captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        logic = metricsPrometheusConnectLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('points the server URL at the Prometheus API of the current project', () => {
        expect(logic.values.serverUrl).toEqual(`${apiHostOrigin()}/api/projects/${MOCK_TEAM_ID}/metrics/prometheus`)
    })

    it('opens the personal API key form with only the metrics read scope', async () => {
        await expectLogic(logic, () => logic.actions.createApiKey()).toDispatchActions(['createApiKey'])

        expect(personalAPIKeysLogic.values.editingKeyId).toEqual('new')
        expect(personalAPIKeysLogic.values.editingKey.scopes).toEqual(['metrics:read'])
        expect(captureSpy).toHaveBeenCalledWith('metrics prometheus api key create clicked')
    })

    it.each([
        {
            name: 'a successful test query',
            mock: () => Promise.resolve({ status: 'success', data: { resultType: 'scalar', result: [0, '2'] } }),
            expected: { status: 'success' },
        },
        {
            name: 'a query the backend rejects',
            mock: () =>
                Promise.reject(
                    new ApiError('failed', 501, undefined, {
                        status: 'error',
                        error: 'PromQL/LogQL query API is not configured',
                    })
                ),
            expected: { status: 'error', message: 'PromQL/LogQL query API is not configured' },
        },
    ])('reports the result of $name', async ({ mock, expected }) => {
        const getSpy = jest.spyOn(api, 'get').mockImplementation(mock as any)

        await expectLogic(logic, () => logic.actions.testConnection()).toFinishAllListeners()

        expect(getSpy).toHaveBeenCalledWith(`api/projects/${MOCK_TEAM_ID}/metrics/prometheus/api/v1/query?query=1%2B1`)
        expect(logic.values.connectionTest).toEqual(expected)
        expect(captureSpy).toHaveBeenCalledWith('metrics prometheus connection tested', {
            success: expected.status === 'success',
        })
    })
})
