import { SeriesNode } from 'scenes/insights/filters/ActionFilter/seriesNode'

import { NodeKind } from '~/queries/schema/schema-general'
import { EntityTypes, PropertyFilterType, PropertyOperator, RetentionEntity } from '~/types'

import { retentionEntityToSeries, seriesToRetentionEntity } from './retentionEntitySeries'

const browserIsChrome = {
    key: '$browser',
    value: ['Chrome'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}

describe('retentionEntitySeries', () => {
    test.each<[string, Record<string, unknown>, Record<string, unknown>]>([
        [
            'an event keeps its name, custom name and properties, and drops its stored uuid and kind',
            {
                id: '$pageview',
                kind: NodeKind.EventsNode,
                type: EntityTypes.EVENTS,
                name: '$pageview',
                custom_name: 'Viewed a page',
                order: 3,
                uuid: '0189e1f0-0000-0000-0000-000000000000',
                properties: [browserIsChrome],
            },
            {
                id: '$pageview',
                type: EntityTypes.EVENTS,
                name: '$pageview',
                custom_name: 'Viewed a page',
                order: 0,
                properties: [browserIsChrome],
            },
        ],
        [
            'all events keep a null id',
            { id: null, type: EntityTypes.EVENTS, name: 'All events' },
            { id: null, type: EntityTypes.EVENTS, name: 'All events', order: 0 },
        ],
        [
            'an action stored with a string id comes back with a numeric id',
            { id: '12', type: EntityTypes.ACTIONS, name: 'Signed up', custom_name: 'Sign up' },
            { id: 12, type: EntityTypes.ACTIONS, name: 'Signed up', custom_name: 'Sign up', order: 0 },
        ],
        [
            'a warehouse table keeps its popover fields',
            {
                id: 'stripe_charges',
                type: EntityTypes.DATA_WAREHOUSE,
                name: 'stripe_charges',
                table_name: 'stripe_charges',
                timestamp_field: 'created_at',
                aggregation_target_field: 'customer_id',
            },
            {
                id: 'stripe_charges',
                type: EntityTypes.DATA_WAREHOUSE,
                name: 'stripe_charges',
                table_name: 'stripe_charges',
                timestamp_field: 'created_at',
                aggregation_target_field: 'customer_id',
                order: 0,
            },
        ],
        [
            'a warehouse table stored only by id gains its table name',
            { id: 'stripe_charges', type: EntityTypes.DATA_WAREHOUSE, timestamp_field: 'created_at' },
            {
                id: 'stripe_charges',
                type: EntityTypes.DATA_WAREHOUSE,
                timestamp_field: 'created_at',
                table_name: 'stripe_charges',
                order: 0,
            },
        ],
        [
            'an entity with no type reads as an event',
            { id: 'signed_up', name: 'signed_up' },
            { id: 'signed_up', type: EntityTypes.EVENTS, name: 'signed_up', order: 0 },
        ],
    ])('%s', (_, stored, expected) => {
        expect(seriesToRetentionEntity(retentionEntityToSeries(stored as RetentionEntity))).toEqual(expected)
    })

    test.each<[string, SeriesNode[], Record<string, unknown> | undefined]>([
        ['no rows store no entity', [], undefined],
        [
            'a row the picker built drops its node version',
            [{ kind: NodeKind.ActionsNode, id: 7, name: 'Purchased', version: 1 } as SeriesNode],
            { id: 7, type: EntityTypes.ACTIONS, name: 'Purchased', order: 0 },
        ],
        [
            'an event row wins over an earlier action row and keeps its own index',
            [
                { kind: NodeKind.ActionsNode, id: 7, name: 'Purchased' },
                { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
            ],
            { id: '$pageview', type: EntityTypes.EVENTS, name: '$pageview', order: 1 },
        ],
    ])('%s', (_, series, expected) => {
        expect(seriesToRetentionEntity(series)).toEqual(expected)
    })

    test('an absent entity shows no row', () => {
        expect(retentionEntityToSeries(undefined)).toEqual([])
    })
})
