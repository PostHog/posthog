import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { router } from 'kea-router'

import { getDefaultQuery } from '~/queries/nodes/InsightViz/utils'
import { initKeaTests } from '~/test/init'
import { InsightType } from '~/types'

import { InsightHomeGuide } from './InsightHomeGuide'

describe('InsightHomeGuide', () => {
    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it('remains visible after the editor replaces the insight hash with a draft query', () => {
        const query = getDefaultQuery(InsightType.FUNNELS, false)
        router.actions.push('/insights/new', { homeGuide: InsightType.FUNNELS }, { q: JSON.stringify(query) })

        render(<InsightHomeGuide query={query} />)

        expect(screen.getByText('Build a funnel')).toBeInTheDocument()
    })

    it('dismisses the guide without losing the draft query or other URL parameters', () => {
        const query = getDefaultQuery(InsightType.FUNNELS, false)
        const draft = JSON.stringify(query)
        router.actions.push('/insights/new', { homeGuide: InsightType.FUNNELS, foo: 'bar' }, { q: draft })
        render(<InsightHomeGuide query={query} />)

        fireEvent.click(screen.getByRole('button', { name: 'close' }))

        expect(screen.queryByText('Build a funnel')).not.toBeInTheDocument()
        expect(router.values.searchParams).toEqual({ foo: 'bar' })
        expect(router.values.hashParams.q).toBe(draft)
    })

    it('only renders a known guide for its matching query type', () => {
        router.actions.push('/insights/new', { homeGuide: InsightType.FUNNELS }, { insight: InsightType.FUNNELS })
        const { rerender } = render(<InsightHomeGuide query={getDefaultQuery(InsightType.PATHS, false)} />)
        expect(screen.queryByText('Build a funnel')).not.toBeInTheDocument()

        router.actions.push('/insights/new', { homeGuide: 'toString' }, { insight: InsightType.FUNNELS })
        rerender(<InsightHomeGuide query={getDefaultQuery(InsightType.FUNNELS, false)} />)
        expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })
})
