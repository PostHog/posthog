import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { WatchFeedItemApi } from '../../generated/api.schemas'
import { watchPicksLogic } from '../watchPicksLogic'
import { WatchPickRankedCard } from './WatchPickRankedCard'

jest.mock('../../components/ObservationThumbnail', () => ({
    ObservationThumbnail: () => <div data-attr="thumbnail" />,
}))

jest.mock('./WatchPickPreview', () => ({
    WatchPickPreview: () => <div data-attr="preview" />,
}))

const item = {
    observation: {
        id: 'observation-1',
        created_at: '2026-10-12T12:00:00Z',
        viewed: false,
        scanner_snapshot: null,
        scanner_result: null,
    },
    reason: { kind: 'recent' },
} as WatchFeedItemApi

describe('WatchPickRankedCard', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({ get: { '/api/projects/:team/vision/scanners/watch_feed/': [200, { results: [] }] } })
    })
    afterEach(() => cleanup())

    it.each(['mouseEnter', 'focus'] as const)('mounts its preview after %s and keeps it for later use', (event) => {
        const { container } = render(
            <BindLogic logic={watchPicksLogic} props={{ logicKey: 'test' }}>
                <WatchPickRankedCard item={item} position={0} surface="top_10" />
            </BindLogic>
        )

        const card = container.querySelector('[data-attr="vision-watch-ranked-card"]')!
        expect(screen.queryByTestId('preview')).toBeNull()
        expect(screen.getAllByTestId('thumbnail')).toHaveLength(1)

        if (event === 'focus') {
            fireEvent.focus(card.querySelector('button')!)
        } else {
            fireEvent.mouseEnter(card)
        }

        expect(screen.getByTestId('preview')).toBeTruthy()
        fireEvent.mouseLeave(card)
        expect(screen.getByTestId('preview')).toBeTruthy()
    })
})
