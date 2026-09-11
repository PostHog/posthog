import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AppContext } from '~/types'

import { heatmapsBrowserLogic } from './heatmapsBrowserLogic'
import { HeatmapsForbiddenURL } from './HeatmapsForbiddenURL'

// The banner used to toast success in the same block that dispatched the save, so a rejected
// `app_urls` PATCH showed "Authorized …" next to the API's permission error.
describe('HeatmapsForbiddenURL', () => {
    const dataUrl = 'https://forbidden.example.com/pricing'
    let priorAppContext: AppContext | undefined

    const mountBanner = (accessLevel = AccessControlLevel.Editor): void => {
        initKeaTests()
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: { web_analytics: accessLevel },
        } as unknown as AppContext

        const logic = heatmapsBrowserLogic()
        logic.mount()
        logic.actions.setDataUrl(dataUrl)
        render(<HeatmapsForbiddenURL />)
    }

    const authorizeButton = (): HTMLButtonElement | null => screen.getAllByText('Authorize URL')[0].closest('button')

    beforeEach(() => {
        jest.restoreAllMocks()
        jest.spyOn(lemonToast, 'success').mockImplementation(() => '' as any)
        jest.spyOn(lemonToast, 'error').mockImplementation(() => '' as any)
        priorAppContext = window.POSTHOG_APP_CONTEXT
    })

    afterEach(() => {
        cleanup()
        window.POSTHOG_APP_CONTEXT = priorAppContext
    })

    it('reports success once the URL is saved', async () => {
        useMocks({ patch: { '/api/environments/:team_id': [200, { app_urls: ['https://forbidden.example.com'] }] } })
        mountBanner()
        fireEvent.click(authorizeButton()!)

        await waitFor(() => expect(lemonToast.success).toHaveBeenCalledWith('Authorized https://forbidden.example.com'))
    })

    it('stays quiet when the save is rejected', async () => {
        useMocks({
            patch: {
                '/api/environments/:team_id': [
                    403,
                    { type: 'authentication_error', code: 'permission_denied', detail: 'Not allowed' },
                ],
            },
        })
        mountBanner()
        fireEvent.click(authorizeButton()!)

        await waitFor(() => expect(lemonToast.error).toHaveBeenCalled())
        expect(lemonToast.success).not.toHaveBeenCalled()
    })

    it('offers no working button to a viewer', () => {
        mountBanner(AccessControlLevel.Viewer)

        expect(authorizeButton()?.getAttribute('aria-disabled')).toBe('true')
    })
})
