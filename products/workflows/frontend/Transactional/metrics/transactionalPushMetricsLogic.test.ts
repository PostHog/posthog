import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { transactionalEmailMetricsLogic } from './transactionalEmailMetricsLogic'
import { transactionalMetricsFiltersLogic } from './transactionalMetricsFiltersLogic'
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

    it('leaves the email Results form in place while push shows, and loads its results again after', async () => {
        const resultsFor: (string | null)[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/transactional_push_log/stats/': [200, { results: [] }],
                '/api/projects/:team_id/transactional_email_log/stats/': [200, { results: [] }],
                '/api/projects/:team_id/transactional_email_log/stats_over_time/': [200, { results: [] }],
                '/api/projects/:team_id/transactional_email_log/results/': ({ request }) => {
                    resultsFor.push(new URL(request.url).searchParams.get('workflow_id'))
                    return [200, { recipients: 1, converted: 0 }]
                },
                '/api/projects/:team_id/transactional_code_emails/': [200, []],
                '/api/projects/:team_id/messaging_templates/': [200, { count: 0, results: [] }],
            },
        })
        initKeaTests()
        const unmountFilters = transactionalMetricsFiltersLogic.mount()
        const email = transactionalEmailMetricsLogic()
        email.mount()
        email.actions.setResultsQuery({ workflowId: 'flow-1', event: 'purchase' })
        email.unmount()
        const push = transactionalPushMetricsLogic()
        push.mount()
        push.unmount()
        email.mount()
        await expectLogic(email).toFinishAllListeners()

        expect(email.values.resultsQuery).toMatchObject({ workflowId: 'flow-1', event: 'purchase' })
        expect(resultsFor).toEqual(['flow-1'])
        email.unmount()
        unmountFilters()
    })
})
