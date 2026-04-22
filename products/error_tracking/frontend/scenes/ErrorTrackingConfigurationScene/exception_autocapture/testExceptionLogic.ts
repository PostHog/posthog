import { actions, kea, listeners, path, reducers } from 'kea'
import posthog from 'posthog-js'

import { ApiRequest } from 'lib/api'

import type { testExceptionLogicType } from './testExceptionLogicType'

export type TestExceptionStatus = 'idle' | 'waiting' | 'received' | 'timeout'

const POLL_INTERVAL_MS = 2000
const POLL_TIMEOUT_MS = 30000
const RECENCY_WINDOW = '5m'

export const testExceptionLogic = kea<testExceptionLogicType>([
    path(['products', 'error_tracking', 'scenes', 'exception_autocapture', 'testExceptionLogic']),
    actions({
        sendTestException: true,
        setStatus: (status: TestExceptionStatus) => ({ status }),
        reset: true,
    }),
    reducers({
        status: [
            'idle' as TestExceptionStatus,
            {
                setStatus: (_, { status }) => status,
                reset: () => 'idle' as TestExceptionStatus,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        sendTestException: async (_, breakpoint) => {
            actions.setStatus('waiting')

            try {
                posthog.captureException(new Error('PostHog test exception — sent from Error tracking settings'), {
                    $exception_source: 'posthog_test_exception',
                })
            } catch {
                // Fall through to polling so a throwing SDK still surfaces a timeout result
            }

            const deadline = Date.now() + POLL_TIMEOUT_MS
            while (Date.now() < deadline) {
                await breakpoint(POLL_INTERVAL_MS)

                const response = await new ApiRequest()
                    .errorTrackingIssuesExists(undefined, { since: RECENCY_WINDOW })
                    .get()
                    .catch(() => null)

                if (response?.exists === true) {
                    actions.setStatus('received')
                    return
                }
            }

            if (values.status === 'waiting') {
                actions.setStatus('timeout')
            }
        },
    })),
])
