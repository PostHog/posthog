import { render } from '@testing-library/react'

import type { SizeProps } from 'lib/components/AutoSizer/AutoSizer'

import { initKeaTests } from '~/test/init'

import { ServicesList } from './ServicesList'

// jsdom measures every element as 0x0, so the real AutoSizer would render nothing.
jest.mock('lib/components/AutoSizer', () => ({
    __esModule: true,
    AutoSizer: ({ renderProp }: { renderProp: (size: SizeProps) => JSX.Element | null }) =>
        renderProp({ width: 800, height: 600 }),
}))

const SERVICES = Array.from({ length: 2400 }, (_, i) => ({
    service_name: `svc-${String(i).padStart(4, '0')}`,
    log_count: 2400 - i,
    error_count: 0,
    error_rate: 0,
}))

describe('ServicesList', () => {
    beforeEach(() => {
        initKeaTests()
    })

    const renderList = (): HTMLElement =>
        render(<ServicesList services={SERVICES} loading={false} searchTerm="" />).container

    it('keeps the DOM bounded by the viewport, not by the number of services', () => {
        const rows = renderList().querySelectorAll('[data-attr="logs-services-row"]')

        // 600px of viewport at 30px rows holds ~18 rows, plus 5 of overscan either side.
        // A count anywhere near 2,400 means the list stopped virtualizing.
        expect(rows.length).toBeGreaterThan(15)
        expect(rows.length).toBeLessThan(40)
    })

    it('links each row to the viewer filtered to that service', () => {
        const href = renderList().querySelector('[data-attr="logs-services-row"] a')?.getAttribute('href')

        expect(href).toContain('activeTab=viewer')
        expect(href).toContain('serviceNames=svc-0000')
    })

    it('states how many services matched and how far they scroll', () => {
        expect(renderList().textContent).toContain('2,400 services, about 134 screens')
    })
})
