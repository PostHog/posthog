import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import {
    isIdleResumeTurnComplete,
    isPiTurnError,
    isSessionUpdate,
    isTurnComplete,
    permissionRequestId,
    turnCompletedSuccessfully,
} from '../../src/lib/side-effects.js'

const cases = JSON.parse(
    readFileSync(new URL('../../../../ee/hogai/sandbox/turn_event_contract.json', import.meta.url), 'utf8')
) as {
    name: string
    event: Record<string, unknown>
    expect: Record<string, boolean>
}[]

const PERMISSION_PARAMS = { requestId: 'perm-1', toolCall: { title: 'Run tests' }, options: [{ optionId: 'allow' }] }

function permissionNotification(params: unknown): Record<string, unknown> {
    return { type: 'notification', notification: { method: '_posthog/permission_request', params } }
}

describe('side-effect predicates', () => {
    // The fixture also carries expectations for predicates only one side has, so
    // each side compares the keys it implements.
    describe('turn event contract', () => {
        it.each(cases)('$name', ({ event, expect: expected }) => {
            const actual = {
                turn_complete: isTurnComplete(event),
                idle_resume: isIdleResumeTurnComplete(event),
                pi_error: isPiTurnError(event),
                session_update: isSessionUpdate(event),
                successful: turnCompletedSuccessfully(event),
            }
            expect(actual).toEqual(Object.fromEntries(Object.keys(actual).map((key) => [key, expected[key]])))
        })
    })

    it.each<[string, Record<string, unknown>, string | null]>([
        ['a bare request', { type: 'permission_request', ...PERMISSION_PARAMS }, 'perm-1'],
        ['a notification request', permissionNotification(PERMISSION_PARAMS), 'perm-1'],
        [
            'a notification request without the notification type',
            { notification: { method: '_posthog/permission_request', params: PERMISSION_PARAMS } },
            'perm-1',
        ],
        [
            'a request with one usable option among malformed ones',
            permissionNotification({
                ...PERMISSION_PARAMS,
                options: ['allow', { optionId: '' }, { optionId: 'allow' }],
            }),
            'perm-1',
        ],
        [
            'another method',
            { type: 'notification', notification: { method: 'session/update', params: PERMISSION_PARAMS } },
            null,
        ],
        ['an empty request id', permissionNotification({ ...PERMISSION_PARAMS, requestId: '' }), null],
        ['a numeric request id', permissionNotification({ ...PERMISSION_PARAMS, requestId: 7 }), null],
        ['a missing tool call', permissionNotification({ ...PERMISSION_PARAMS, toolCall: undefined }), null],
        ['an array tool call', permissionNotification({ ...PERMISSION_PARAMS, toolCall: [] }), null],
        [
            'options without a non-empty string optionId',
            permissionNotification({ ...PERMISSION_PARAMS, options: [{ optionId: '' }, { optionId: 1 }, 'allow'] }),
            null,
        ],
        ['array params', permissionNotification([PERMISSION_PARAMS]), null],
        [
            'a bare type that wraps a notification request',
            { ...permissionNotification(PERMISSION_PARAMS), type: 'permission_request' },
            null,
        ],
    ])('permissionRequestId reads %s as %s', (_label, event, expected) => {
        expect(permissionRequestId(event)).toBe(expected)
    })
})
