import type { VisionActionApi } from '../../generated/api.schemas'
import { deliverySummary } from './VisionActionsTab'

describe('deliverySummary', () => {
    const withTargets = (delivery_config: unknown): VisionActionApi =>
        ({ delivery_config }) as unknown as VisionActionApi

    it.each([
        ['no targets', [], '—'],
        ['webhook target', [{ type: 'webhook', url: 'https://example.com/hook' }], 'Webhook'],
        // The `${id}|#${name}` composite surfaces the friendly channel name.
        ['slack with named channel', [{ type: 'slack', integration_id: 1, channel: 'C1|#general' }], '#general'],
        // An id-only channel (older rows) falls back to "Slack" rather than leaking a bare id.
        ['slack with bare id', [{ type: 'slack', integration_id: 1, channel: 'C1' }], 'Slack'],
        [
            'mixed slack and webhook',
            [
                { type: 'slack', integration_id: 1, channel: 'C1|#general' },
                { type: 'webhook', url: 'https://example.com/hook' },
            ],
            '#general, Webhook',
        ],
    ])('summarizes %s', (_label, delivery_config, expected) => {
        expect(deliverySummary(withTargets(delivery_config))).toBe(expected)
    })
})
