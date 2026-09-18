import type { HogFlow } from './hogflows/types'
import { findMatchingWorkflowSteps } from './workflowSearchMatches'

function workflowWith(overrides: Partial<HogFlow>): HogFlow {
    return {
        id: 'flow-1',
        name: 'Billing',
        description: '',
        actions: [],
        edges: [],
        ...overrides,
    } as unknown as HogFlow
}

function emailAction(id: string, name: string, value: Record<string, unknown>): HogFlow['actions'][number] {
    return {
        id,
        name,
        type: 'function_email',
        config: { template_id: 'template-email', inputs: { email: { value } } },
    } as unknown as HogFlow['actions'][number]
}

const invoiceEmail = emailAction('email_1', 'Monthly invoice email', {
    subject: 'Your invoice for March is ready',
    preheader: 'Download it from your billing page',
    html: '<table class="footer-links"><tr><td>Your invoice is attached.</td></tr></table>',
})

describe('findMatchingWorkflowSteps', () => {
    test.each([
        ['step name', 'monthly invoice', { actionId: 'email_1', field: 'Step', value: 'Monthly invoice email' }],
        [
            'email subject',
            'FOR MARCH',
            { actionId: 'email_1', field: 'Email subject', value: 'Your invoice for March is ready' },
        ],
        [
            'email preheader',
            'billing page',
            { actionId: 'email_1', field: 'Email preheader', value: 'Download it from your billing page' },
        ],
    ])('matches the %s', (_field, search, expected) => {
        const workflow = workflowWith({ actions: [invoiceEmail] })
        expect(findMatchingWorkflowSteps(workflow, search)).toEqual([expected])
    })

    test.each([
        ['the search is blank', '   '],
        ['the email body matched', 'footer-links'],
        ['the search has regex characters that appear nowhere', 'invoice (march)'],
    ])('returns nothing when %s', (_reason, search) => {
        const workflow = workflowWith({ actions: [invoiceEmail] })
        expect(findMatchingWorkflowSteps(workflow, search)).toEqual([])
    })

    it('treats a space in the search as any separator, like the list API does', () => {
        const workflow = workflowWith({
            actions: [emailAction('email_1', 'Step', { subject: 'Your invoice_for-March' })],
        })
        expect(findMatchingWorkflowSteps(workflow, 'invoice for march')).toHaveLength(1)
    })

    it('returns nothing when the workflow name or description already explains the match', () => {
        const workflow = workflowWith({ name: 'Invoice reminders', actions: [invoiceEmail] })
        expect(findMatchingWorkflowSteps(workflow, 'invoice')).toEqual([])
    })

    it('includes a step staged in the draft once, preferring the live version when both match', () => {
        const workflow = workflowWith({
            actions: [invoiceEmail],
            draft: {
                actions: [
                    emailAction('email_1', 'Monthly invoice email', { subject: 'Your invoice for April is ready' }),
                    emailAction('email_2', 'Access email', { subject: 'Your beta access starts today' }),
                ],
            },
        })
        expect(findMatchingWorkflowSteps(workflow, 'invoice for')).toEqual([
            { actionId: 'email_1', field: 'Email subject', value: 'Your invoice for March is ready' },
        ])
        expect(findMatchingWorkflowSteps(workflow, 'beta access')).toEqual([
            { actionId: 'email_2', field: 'Email subject', value: 'Your beta access starts today' },
        ])
        expect(findMatchingWorkflowSteps(workflow, 'for april')).toEqual([
            { actionId: 'email_1', field: 'Email subject', value: 'Your invoice for April is ready' },
        ])
    })
})
