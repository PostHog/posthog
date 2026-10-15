import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import api from 'lib/api'
import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { FilterPanel } from './FilterPanel'

describe('FilterPanel', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/heatmaps/': { results: [], count: 0, next: null, previous: null },
            },
        })
        initKeaTests()
        jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [['click', 390, 90]] })
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('diagnoses an empty result before Display opens and keeps width shares ready', async () => {
        render(
            <Provider>
                <FilterPanel />
            </Provider>
        )

        act(() => heatmapDataLogic({ context: 'in-app' }).actions.setHref('https://example.com/pricing'))

        expect(await screen.findByText('Show 375px')).toBeInTheDocument()
        expect(screen.queryByText('Screen width')).not.toBeInTheDocument()

        fireEvent.click(screen.getByText('Display'))
        fireEvent.click(screen.getByLabelText('Screen width'))

        expect(screen.getAllByText('100%').length).toBeGreaterThan(0)
    })
})
