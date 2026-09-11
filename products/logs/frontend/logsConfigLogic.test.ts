import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TeamLogsConfigApi } from './generated/api.schemas'
import { logsConfigLogic } from './logsConfigLogic'

const config: TeamLogsConfigApi = {
    logs_distinct_id_attribute_key: 'posthogDistinctId',
    logs_distinct_id_attribute_keys: ['posthogDistinctId'],
    logs_session_id_attribute_keys: ['sessionId'],
    logs_pattern_message_keys: ['message', 'msg', 'event'],
}

describe('logsConfigLogic pattern message keys', () => {
    let logic: ReturnType<typeof logsConfigLogic.build>
    let patch: jest.Mock
    let submittedPatch: unknown

    beforeEach(async () => {
        submittedPatch = undefined
        patch = jest.fn(async ({ request }) => {
            submittedPatch = await request.json()
            return [200, { ...config, ...(submittedPatch as object) }]
        })
        useMocks({
            get: { '/api/projects/:id/logs_config/': config },
            patch: { '/api/projects/:id/logs_config/': patch },
        })
        initKeaTests()
        logic = logsConfigLogic()
        logic.mount()
        await expectLogic(logic)
            .toDispatchActions(['loadLogsConfigSuccess'])
            .toMatchValues({
                patternMessageKeys: { keys: config.logs_pattern_message_keys },
                patternMessageKeysChanged: false,
            })
    })

    afterEach(() => {
        logic?.unmount()
    })

    it.each([
        ['an empty list', [], []],
        ['reordered keys', ['msg', 'message'], ['msg', 'message']],
        ['trimmed literal keys', [' log.message ', 'message'], ['log.message', 'message']],
    ])('saves %s without changing correlation settings', async (_name, keys, expected) => {
        logic.actions.setPatternMessageKeysValue('keys', keys)
        await expectLogic(logic, () => logic.actions.submitPatternMessageKeys())
            .toDispatchActions(['updateLogsConfigSuccess', 'submitPatternMessageKeysSuccess'])
            .toMatchValues({
                logsConfig: { ...config, logs_pattern_message_keys: expected },
                patternMessageKeys: { keys: expected },
                patternMessageKeysChanged: false,
                isPatternMessageKeysSubmitting: false,
            })
        expect(patch).toHaveBeenCalledTimes(1)
        expect(submittedPatch).toEqual({ logs_pattern_message_keys: expected })
    })

    it.each([
        [['message', ' message '], 'Keys must be unique.'],
        [[' '], 'Keys cannot be blank.'],
        [['x'.repeat(201)], 'Each key must be 200 characters or fewer.'],
        [Array.from({ length: 11 }, (_, index) => `key${index}`), 'Use at most 10 keys.'],
    ])('rejects invalid keys %j before saving', async (keys, error) => {
        logic.actions.setPatternMessageKeysValue('keys', keys)
        await expectLogic(logic, () => logic.actions.submitPatternMessageKeys()).toMatchValues({
            patternMessageKeysValidationErrors: { keys: [error] },
            isPatternMessageKeysSubmitting: false,
        })
        expect(patch).not.toHaveBeenCalled()
    })

    it('preserves the draft and allows retrying after a failed save', async () => {
        patch.mockResolvedValueOnce([500, { detail: 'Could not save settings' }])
        logic.actions.setPatternMessageKeysValue('keys', [])
        await expectLogic(logic, () => logic.actions.submitPatternMessageKeys())
            .toDispatchActions(['submitPatternMessageKeysFailure'])
            .toMatchValues({
                logsConfig: config,
                patternMessageKeys: { keys: [] },
                patternMessageKeysChanged: true,
                isPatternMessageKeysSubmitting: false,
            })
        await expectLogic(logic, () => logic.actions.submitPatternMessageKeys()).toDispatchActions([
            'submitPatternMessageKeysSuccess',
        ])
    })
})
