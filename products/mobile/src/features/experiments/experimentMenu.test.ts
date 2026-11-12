import type { ExperimentApi } from '@/api/experiments'

import { experimentMenuItems } from './experimentMenu'

function experiment(status: ExperimentApi['status'], archived = false): ExperimentApi {
    return {
        id: 7,
        name: 'Checkout CTA copy',
        status,
        archived,
        start_date: status === 'draft' ? null : '2026-11-01T00:00:00Z',
        end_date: status === 'stopped' ? '2026-11-04T00:00:00Z' : null,
        feature_flag_key: 'checkout-cta',
        feature_flag: { id: 3, team_id: 1, key: 'checkout-cta', active: status !== 'paused', evaluation_contexts: [] },
    } as unknown as ExperimentApi
}

describe('experimentMenuItems', () => {
    it.each<[string, ExperimentApi, string[]]>([
        ['running', experiment('running'), ['pause']],
        ['frozen', experiment('exposure_frozen'), ['pause']],
        ['paused', experiment('paused'), ['resume']],
        ['complete', experiment('stopped'), ['edit-conclusion', 'archive']],
        ['archived', experiment('stopped', true), ['edit-conclusion']],
        ['draft', experiment('draft'), []],
    ])('offers only the verbs the server accepts when %s', (_name, value, verbs) => {
        const keys = experimentMenuItems(value, { onOpenSheet: jest.fn() }).map((item) => item.key)
        expect(keys).toEqual(['web', 'copy', 'flag', ...verbs])
    })

    it('disables the web rows without a handler and opens the sheet for a verb', () => {
        const onOpenSheet = jest.fn()
        const items = experimentMenuItems(experiment('stopped'), { onOpenSheet, onOpenWeb: jest.fn() })
        expect(items.filter((item) => item.disabled).map((item) => item.key)).toEqual(['copy', 'flag'])
        items.find((item) => item.key === 'edit-conclusion')?.onPress()
        expect(onOpenSheet).toHaveBeenCalledWith('edit_conclusion')
    })
})
