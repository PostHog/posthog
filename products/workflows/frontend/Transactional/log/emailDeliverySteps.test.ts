import type {
    TransactionalEmailLogDetailApi,
    TransactionalEmailLogEventApi,
} from 'products/messaging/frontend/generated/api.schemas'

import { buildDeliverySteps } from './emailDeliverySteps'

function email(
    status: TransactionalEmailLogDetailApi['status'],
    kinds: TransactionalEmailLogEventApi['kind'][],
    sensitive = false
): TransactionalEmailLogDetailApi {
    return {
        message_id: '01977a3c-9a00-7000-8000-000000000001',
        created_at: '2026-06-15T09:00:00Z',
        status,
        status_at: '2026-06-15T09:00:00Z',
        reason: null,
        recipient: 'maya@example.com',
        workflow_id: 'workflow',
        template_id: 'template',
        template_name: 'Welcome email',
        sending_domain: 'example.com',
        opened: kinds.includes('opened'),
        clicked: kinds.includes('clicked'),
        timeline: kinds.map((kind, index) => ({
            kind,
            at: `2026-06-15T09:00:0${index}Z`,
            reason: kind === 'bounced' ? 'hard' : null,
        })),
        subject: 'Welcome',
        distinct_id: 'user_1',
        action_id: 'action_1',
        sensitive,
    }
}

describe('buildDeliverySteps', () => {
    test.each([
        [
            'opened and clicked',
            email('delivered', ['queued', 'sent', 'delivered', 'opened', 'clicked']),
            ['sent:done', 'delivered:done', 'opened:done', 'clicked:done'],
        ],
        [
            'delivered, not opened yet',
            email('delivered', ['queued', 'sent', 'delivered']),
            ['sent:done', 'delivered:done', 'opened:pending', 'clicked:pending'],
        ],
        [
            'still queued',
            email('queued', ['queued']),
            ['queued:done', 'sent:pending', 'delivered:pending', 'opened:pending', 'clicked:pending'],
        ],
        ['bounce stops the steps', email('bounced', ['queued', 'sent', 'bounced']), ['sent:done', 'bounced:failed']],
        [
            'spam report stops the steps',
            email('complained', ['queued', 'sent', 'delivered', 'complained', 'opened']),
            ['sent:done', 'delivered:done', 'complained:failed'],
        ],
        ['failed', email('failed', ['queued', 'failed']), ['queued:done', 'failed:failed']],
        ['rejected after it was sent', email('failed', ['queued', 'sent', 'failed']), ['sent:done', 'failed:failed']],
        [
            'sent row arriving after delivered',
            email('delivered', ['queued', 'delivered', 'sent']),
            ['sent:done', 'delivered:done', 'opened:pending', 'clicked:pending'],
        ],
        [
            'sensitive, so a click can never be recorded',
            email('delivered', ['queued', 'sent', 'delivered', 'opened'], true),
            ['sent:done', 'delivered:done', 'opened:done', 'clicked:untracked'],
        ],
        [
            'sensitive with a click recorded anyway',
            email('delivered', ['queued', 'sent', 'delivered', 'clicked'], true),
            ['sent:done', 'delivered:done', 'opened:pending', 'clicked:done'],
        ],
        [
            'sensitive and bounced',
            email('bounced', ['queued', 'sent', 'bounced'], true),
            ['sent:done', 'bounced:failed'],
        ],
    ])('%s', (_, input, expected) => {
        expect(buildDeliverySteps(input).map((step) => `${step.key}:${step.state}`)).toEqual(expected)
    })

    test('a bounce after a failed attempt shows when it bounced, not when the attempt failed', () => {
        const steps = buildDeliverySteps(email('bounced', ['queued', 'failed', 'sent', 'bounced']))

        expect(steps[steps.length - 1]).toMatchObject({ key: 'bounced', at: '2026-06-15T09:00:03Z' })
    })
})
