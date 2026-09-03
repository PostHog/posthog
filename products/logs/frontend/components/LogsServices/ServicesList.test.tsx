import { render } from '@testing-library/react'

import type { SizeProps } from 'lib/components/AutoSizer/AutoSizer'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import type { ServiceRow } from './logsServicesLogic'
import { ServicesList } from './ServicesList'

// jsdom measures every element as 0x0, so the real AutoSizer would render nothing.
jest.mock('lib/components/AutoSizer', () => ({
    __esModule: true,
    AutoSizer: ({ renderProp }: { renderProp: (size: SizeProps) => JSX.Element | null }) =>
        renderProp({ width: 800, height: 600 }),
}))

const service = (name: string): ServiceRow => ({
    service_name: name,
    log_count: 1,
    error_count: 0,
    error_rate: 0,
})

const SERVICES = Array.from({ length: 2400 }, (_, i) => ({
    ...service(`svc-${String(i).padStart(4, '0')}`),
    log_count: 2400 - i,
}))

describe('ServicesList', () => {
    beforeEach(() => {
        initKeaTests()
    })

    const renderList = (services: ServiceRow[] = SERVICES, dateFrom = '-1h'): HTMLElement =>
        render(<ServicesList services={services} loading={false} searchTerm="" dateFrom={dateFrom} />).container

    /** The metrics link is gated on the alpha flag and on metrics access, so a row only shows it for both. */
    const enableMetricsLink = (): void => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.Metrics]: AccessControlLevel.Viewer,
            },
        } as AppContext
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.METRICS]: true })
    }

    it('keeps the DOM bounded by the viewport, not by the number of services', () => {
        const rows = renderList().querySelectorAll('[data-attr="logs-services-row"]')

        // 600px of viewport at 30px rows holds ~18 rows, plus 5 of overscan either side.
        // A count anywhere near 2,400 means the list stopped virtualizing.
        expect(rows.length).toBeGreaterThan(15)
        expect(rows.length).toBeLessThan(40)
    })

    it('carries the whole service name into the viewer link, commas and all', () => {
        const href = renderList([service('checkout,v2')])
            .querySelector('[data-attr="logs-services-row"] a')
            ?.getAttribute('href')

        expect(href).toContain('activeTab=viewer')
        // A scalar here would come back out of the URL as two services.
        expect(href).toContain(`serviceNames=${encodeURIComponent('["checkout,v2"]')}`)
    })

    it('leaves the no-service row unlinked, because no filter can express it', () => {
        const row = renderList([service('(no service)')]).querySelector('[data-attr="logs-services-row"]')

        expect(row?.textContent).toContain('(no service)')
        expect(row?.querySelector('a')).toBeNull()
        expect(row?.querySelector('[data-attr="logs-services-row-share"]')).toBeNull()
    })

    it('states how many services matched and how far they scroll', () => {
        expect(renderList().textContent).toContain('2,400 services, about 134 screens')
    })

    // Metrics defaults to the last hour. Without the window the user picked here, a service
    // busy over seven days opens on an hour of chart and reads as though it has no traffic.
    it('opens metrics on the window the services list is showing', () => {
        enableMetricsLink()
        const href = renderList([service('checkout')], '-7d')
            .querySelector('[data-attr="logs-services-row-metrics"]')
            ?.getAttribute('href')

        expect(href).toContain('dateFrom=-7d')
    })
})
