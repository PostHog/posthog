import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'

import { initKeaTests } from '~/test/init'

import {
    buildRecordingFiltersForUrl,
    buildRecordingMatchingEventFiltersForUrl,
    buildRecordingsQueryForUrl,
    heatmapRecordingFallbackLogic,
} from './heatmapRecordingFallbackLogic'

describe('heatmapRecordingFallbackLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('searches recordings by pages actually visited during the session, not just session start', () => {
        const query = buildRecordingsQueryForUrl('https://example.com/pricing')
        expect(query.properties).toEqual([
            {
                type: 'recording',
                key: 'visited_page',
                operator: 'icontains',
                value: ['https://example.com/pricing'],
            },
        ])
        expect(query.order).toBe('start_time')
        expect(query.order_direction).toBe('DESC')
        expect(query.kind).toBe('RecordingsQuery')
        expect(query.limit).toBe(3)
        expect(query.date_from).toBe('-30d')
    })

    it('opens Session replay with the same visited-page and lookback filters', () => {
        expect(buildRecordingFiltersForUrl('https://example.com/pricing')).toEqual({
            date_from: '-30d',
            filter_group: {
                type: 'AND',
                values: [
                    {
                        type: 'AND',
                        values: [
                            {
                                type: 'recording',
                                key: 'visited_page',
                                operator: 'icontains',
                                value: ['https://example.com/pricing'],
                            },
                        ],
                    },
                ],
            },
        })
    })

    it('finds the first matching page event when choosing a recording background', () => {
        expect(buildRecordingMatchingEventFiltersForUrl('https://example.com/pricing')).toEqual({
            date_from: '-30d',
            duration: [],
            filter_group: {
                type: 'AND',
                values: [
                    {
                        type: 'AND',
                        values: [
                            {
                                type: 'event',
                                key: '$current_url',
                                operator: 'icontains',
                                value: ['https://example.com/pricing'],
                            },
                        ],
                    },
                ],
            },
        })
    })

    it('opens a guided player with the target page and matching count', async () => {
        const recordings = [{ id: 'recording-one' }, { id: 'recording-two' }]
        jest.spyOn(api.recordings, 'list').mockResolvedValue({ results: recordings } as any)
        const modalLogic = sessionPlayerModalLogic
        const logic = heatmapRecordingFallbackLogic({
            url: 'https://example.com/pricing',
            selectionMode: 'guided',
        })
        modalLogic.mount()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openRecording(recordings[0])
        await expectLogic(logic).toFinishAllListeners()

        expect(modalLogic.values.modalContext).toEqual({
            type: 'heatmap-background-selection',
            targetUrl: 'https://example.com/pricing',
            matchingRecordingCount: 2,
        })
    })
})
