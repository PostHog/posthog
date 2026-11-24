import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { transactionalPushMetricsLogic } from './transactionalPushMetricsLogic'

describe('transactionalPushMetricsLogic', () => {
    it('loads only push numbers, on open and when the period changes', async () => {
        const requested: string[] = []
        const answer = ({ request }: { request: Request }): [number, unknown] => {
            requested.push(new URL(request.url).pathname.split('/').slice(4).join('/'))
            return [200, { results: [] }]
        }
        useMocks({
            get: {
                '/api/projects/:team_id/transactional_push_log/stats/': answer,
                '/api/projects/:team_id/transactional_email_log/stats/': answer,
                '/api/projects/:team_id/transactional_email_log/stats_over_time/': answer,
                '/api/projects/:team_id/transactional_code_emails/': answer,
            },
        })
        initKeaTests()
        const logic = transactionalPushMetricsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setHours(24)
        await expectLogic(logic).toFinishAllListeners()

        expect(requested).toEqual(['transactional_push_log/stats/', 'transactional_push_log/stats/'])
        logic.unmount()
    })
})
