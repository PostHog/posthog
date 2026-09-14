import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { metricsNamesRetrieve, metricsValuesRetrieve } from '../generated/api'
import { MetricsCatalog } from './MetricsCatalog'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    metricsNamesRetrieve: jest.fn(),
    metricsValuesRetrieve: jest.fn(),
    metricsQueryCreate: jest.fn(),
}))

const CATALOG_ITEMS = [
    { name: 'http.server.duration', metric_type: 'histogram' },
    { name: 'queue.depth', metric_type: 'gauge' },
]

// Stands in for the browser's observer so a test can say which cards are in view.
class FakeIntersectionObserver {
    static observers: { callback: IntersectionObserverCallback; elements: Element[] }[] = []
    private entry: { callback: IntersectionObserverCallback; elements: Element[] }

    constructor(callback: IntersectionObserverCallback) {
        this.entry = { callback, elements: [] }
        FakeIntersectionObserver.observers.push(this.entry)
    }

    observe(element: Element): void {
        this.entry.elements.push(element)
    }

    disconnect(): void {
        this.entry.elements = []
    }

    unobserve(): void {}
}

const scrollIntoView = (testId: string): void => {
    for (const observer of FakeIntersectionObserver.observers) {
        for (const element of observer.elements) {
            if (element.getAttribute('data-attr') === testId) {
                observer.callback([{ isIntersecting: true, target: element } as IntersectionObserverEntry], null as any)
            }
        }
    }
}

// The catalog only lists names, so each card asks for its own sparkline. That
// request must wait until the card is near the viewport, or the lazy load is
// no cheaper than the one query over every metric it replaced.
describe('MetricsCatalog', () => {
    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.Metrics]: AccessControlLevel.Viewer,
            },
        } as AppContext
        initKeaTests()
        FakeIntersectionObserver.observers = []
        window.IntersectionObserver = FakeIntersectionObserver as unknown as typeof IntersectionObserver
        jest.mocked(metricsNamesRetrieve).mockResolvedValue({ results: CATALOG_ITEMS } as any)
        jest.mocked(metricsValuesRetrieve).mockReset()
        jest.mocked(metricsValuesRetrieve).mockResolvedValue({ results: [] } as any)
    })

    afterEach(() => cleanup())

    it('requests a card sparkline only once that card scrolls into view', async () => {
        render(
            <Provider>
                <MetricsCatalog />
            </Provider>
        )
        expect(await screen.findByText('queue.depth')).toBeInTheDocument()
        expect(jest.mocked(metricsValuesRetrieve)).not.toHaveBeenCalled()

        await act(async () => {
            scrollIntoView('metrics-catalog-card-queue.depth')
        })

        expect(jest.mocked(metricsValuesRetrieve)).toHaveBeenCalledTimes(1)
        expect(jest.mocked(metricsValuesRetrieve)).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ value: 'queue.depth', limit: 1 })
        )
    })
})
