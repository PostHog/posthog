import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { ViewServiceMetricsButton } from './ViewServiceMetricsButton'

describe('ViewServiceMetricsButton', () => {
    const setAccess = (level: AccessControlLevel | undefined): void => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.Metrics]: level,
            },
        } as AppContext
    }

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
    })

    afterEach(() => cleanup())

    const renderButton = ({ flagOn = true, ...props }: any): void => {
        featureFlagLogic.actions.setFeatureFlags([], flagOn ? { [FEATURE_FLAGS.METRICS]: true } : {})
        render(
            <Provider>
                <ViewServiceMetricsButton {...props} />
            </Provider>
        )
    }

    // Metrics is in private alpha behind a flag. A link rendered without it lands on the waitlist
    // screen, not a chart — a dead end reached from a GA product.
    it.each([
        ['the metrics flag is off', { serviceName: 'checkout', flagOn: false }, AccessControlLevel.Viewer],
        ['the user cannot view metrics', { serviceName: 'checkout' }, undefined],
        ['there is no service name', { serviceName: '' }, AccessControlLevel.Viewer],
    ])('renders nothing when %s', (_name, props, level) => {
        setAccess(level)
        renderButton(props)
        expect(screen.queryByText('View metrics')).not.toBeInTheDocument()
    })

    it('links to the service, carrying the window the caller was on', () => {
        setAccess(AccessControlLevel.Viewer)
        renderButton({ serviceName: 'checkout', dateFrom: '-30m' })

        const href = screen.getByText('View metrics').closest('a')?.getAttribute('href')
        expect(href).toContain('dateFrom=-30m')
        expect(href).toContain('checkout')
    })
})
