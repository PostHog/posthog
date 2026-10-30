import { buildInboxSourceChoices, singleInboxSourceSelection } from './inboxSourceFilter'

describe('inboxSourceFilter', () => {
    it('lists configured products and every scout, and keeps stale selections visible', () => {
        const choices = buildInboxSourceChoices({
            sourceConfigs: [
                { source_product: 'error_tracking' },
                { source_product: 'error_tracking' },
                { source_product: 'signals_scout' },
            ],
            scoutConfigs: [
                { skill_name: 'signals-scout-error-tracking' },
                { skill_name: 'team-checkout-a', display_name: 'Checkout' },
                { skill_name: 'team-checkout-b', display_name: 'Checkout' },
            ],
            sourceProductFilter: ['zendesk'],
            scoutFilter: ['deleted-scout'],
        })

        expect(choices.sources.map(({ value, label, unavailable }) => [value, label, unavailable])).toEqual([
            ['error_tracking', 'Error tracking', false],
            ['zendesk', 'Zendesk', true],
        ])
        expect(choices.scouts.map(({ value, label, unavailable }) => [value, label, unavailable])).toEqual([
            ['team-checkout-a', 'Checkout (team-checkout-a)', false],
            ['team-checkout-b', 'Checkout (team-checkout-b)', false],
            ['deleted-scout', 'Deleted scout', true],
            ['signals-scout-error-tracking', 'Error tracking', false],
        ])
    })

    it.each([
        [['logs'], [], { kind: 'source_product', value: 'logs' }],
        [[], ['my-scout'], { kind: 'scout', value: 'my-scout' }],
        [[], [], null],
        // An old shared link can combine several values. No single choice represents it.
        [['logs', 'github'], [], null],
        [['logs'], ['my-scout'], null],
    ])('reads %p and %p as one selection: %p', (sourceProductFilter, scoutFilter, expected) => {
        expect(singleInboxSourceSelection(sourceProductFilter, scoutFilter)).toEqual(expected)
    })
})
