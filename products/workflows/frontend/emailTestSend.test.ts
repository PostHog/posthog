import { TEST_EMAIL_ACTION_ID, buildSingleEmailTestFlow, findTestSendSkipReason } from './emailTestSend'
import { HogflowTestResult } from './Workflows/hogflows/steps/types'

const result = (partial: Partial<HogflowTestResult>): HogflowTestResult =>
    ({ status: 'success', nextActionId: null, ...partial }) as HogflowTestResult

const log = (message: string): any => ({ level: 'info', timestamp: '2026-01-01T00:00:00Z', message })

const emailContent = {
    to: { email: '{{ person.properties.email }}', name: '' },
    from: { integrationId: 7 },
    cc: 'team@example.com',
    bcc: 'archive@example.com',
    subject: 'Welcome',
    html: '<p>Hello</p>',
    text: 'Hello',
}

describe('emailTestSend', () => {
    describe('buildSingleEmailTestFlow', () => {
        it('replaces the content recipient with the typed address and drops cc and bcc', () => {
            const flow = buildSingleEmailTestFlow({
                email: emailContent,
                recipientEmail: 'tester@example.com',
                name: 'Onboarding',
                teamId: 2,
            })

            const emailAction = flow.actions.find((action) => action.id === TEST_EMAIL_ACTION_ID)
            expect((emailAction as any).config.inputs.email.value).toMatchObject({
                to: { email: 'tester@example.com', name: '' },
                cc: '',
                bcc: '',
                subject: 'Welcome',
                from: { integrationId: 7 },
            })
        })

        it('holds nothing but the trigger, the one email, and the exit', () => {
            const flow = buildSingleEmailTestFlow({
                email: emailContent,
                recipientEmail: 'tester@example.com',
                name: 'Onboarding',
                teamId: 2,
            })

            expect(flow.actions.map((action) => action.type)).toEqual(['trigger', 'function_email', 'exit'])
            expect(flow.edges.map((edge) => [edge.from, edge.to])).toEqual([
                ['trigger_node', TEST_EMAIL_ACTION_ID],
                [TEST_EMAIL_ACTION_ID, 'exit_node'],
            ])
        })
    })

    describe('findTestSendSkipReason', () => {
        it('finds the reason a declined send reports, even though the run says success', () => {
            // The worker declines the send but finishes the step, so status alone would read as sent.
            const reason =
                'Skipping send: the domain "example.com" has no reachable mail servers, so this message would hard bounce.'
            expect(
                findTestSendSkipReason(
                    result({ status: 'success', logs: [log('Executing action [Action:send_test_email]'), log(reason)] })
                )
            ).toBe(reason)
        })

        it.each([
            [
                'a delivered send',
                result({ status: 'success', logs: [log('Executing action [Action:send_test_email]')] }),
            ],
            ['a run with no logs', result({ status: 'success' })],
            ['no result at all', null],
        ])('reports no reason for %s', (_name, input) => {
            expect(findTestSendSkipReason(input)).toBeUndefined()
        })
    })
})
