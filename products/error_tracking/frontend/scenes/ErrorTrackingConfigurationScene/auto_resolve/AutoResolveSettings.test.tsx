import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import * as api from 'products/error_tracking/frontend/generated/api'
import type { ErrorTrackingSettingsApi } from 'products/error_tracking/frontend/generated/api.schemas'

import { AutoResolveSettings } from './AutoResolveSettings'

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (error: Error) => void } {
    let resolve!: (value: T) => void
    let reject!: (error: Error) => void
    const promise = new Promise<T>((resolvePromise, rejectPromise) => {
        resolve = resolvePromise
        reject = rejectPromise
    })
    return { promise, resolve, reject }
}

describe('AutoResolveSettings', () => {
    let originalAppContext: typeof window.POSTHOG_APP_CONTEXT

    beforeEach(() => {
        originalAppContext = window.POSTHOG_APP_CONTEXT
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, id: 1 })
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT!,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT!.resource_access_control!,
                error_tracking: AccessControlLevel.Editor,
            },
        }
        silenceKeaLoadersErrors()
        jest.spyOn(lemonToast, 'success').mockImplementation(() => '')
        jest.spyOn(lemonToast, 'error').mockImplementation(() => '')
    })

    afterEach(() => {
        cleanup()
        resumeKeaLoadersErrors()
        jest.restoreAllMocks()
        window.POSTHOG_APP_CONTEXT = originalAppContext
    })

    it('keeps the form unavailable after a failed initial load and retries the settings request', async () => {
        const request = deferred<ErrorTrackingSettingsApi>()
        const retrieve = jest
            .spyOn(api, 'errorTrackingSettingsRetrieveSettingsRetrieve')
            .mockImplementationOnce(() => request.promise)
            .mockResolvedValue({ auto_resolve_after_days: 7 })
        const update = jest.spyOn(api, 'errorTrackingSettingsUpdateSettingsPartialUpdate').mockResolvedValue({})
        const { container } = render(<AutoResolveSettings />)

        expect(container.querySelector('[data-attr="error-tracking-auto-resolve-toggle"]')).toBeNull()
        expect(container.querySelector('[data-attr="error-tracking-auto-resolve-save"]')).toBeNull()

        await act(async () => request.reject(new Error('Request failed')))

        expect(screen.getByText("Couldn't load the auto-resolve settings. Try again.")).toBeInTheDocument()
        expect(container.querySelector('[data-attr="error-tracking-auto-resolve-save"]')).toBeNull()

        fireEvent.click(screen.getAllByText('Try again')[0])

        await waitFor(() => expect(screen.getByRole('spinbutton')).toHaveValue(7))
        expect(retrieve).toHaveBeenCalledTimes(2)
        expect(update).not.toHaveBeenCalled()
        expect(container.querySelector('[data-attr="error-tracking-auto-resolve-save"]')).toHaveAttribute(
            'aria-disabled',
            'true'
        )
    })

    it.each(['load', 'save'] as const)(
        'isolates a late %s response when the selected project changes',
        async (operation) => {
            const firstRequest = deferred<ErrorTrackingSettingsApi>()
            const secondRequest = deferred<ErrorTrackingSettingsApi>()
            jest.spyOn(api, 'errorTrackingSettingsRetrieveSettingsRetrieve').mockImplementation((teamId) =>
                teamId === '1'
                    ? operation === 'load'
                        ? firstRequest.promise
                        : Promise.resolve({ auto_resolve_after_days: 7 })
                    : secondRequest.promise
            )
            const update = jest
                .spyOn(api, 'errorTrackingSettingsUpdateSettingsPartialUpdate')
                .mockImplementation((teamId, settings) =>
                    teamId === '1' ? firstRequest.promise : Promise.resolve(settings ?? {})
                )
            const { container } = render(<AutoResolveSettings />)

            if (operation === 'save') {
                const daysInput = await screen.findByRole('spinbutton')
                fireEvent.change(daysInput, { target: { value: '12' } })
                await act(async () => fireEvent.click(screen.getByText('Save')))
            }
            expect(update.mock.calls).toEqual(operation === 'save' ? [['1', { auto_resolve_after_days: 12 }]] : [])

            act(() => teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: 2 }))

            expect(container.querySelector('[data-attr="error-tracking-auto-resolve-save"]')).toBeNull()
            await act(async () => secondRequest.resolve({ auto_resolve_after_days: 30 }))
            await waitFor(() => expect(screen.getByRole('spinbutton')).toHaveValue(30))

            await act(async () => firstRequest.resolve({ auto_resolve_after_days: 12 }))

            expect(screen.getByRole('spinbutton')).toHaveValue(30)
            expect(container.querySelector('[data-attr="error-tracking-auto-resolve-save"]')).toHaveAttribute(
                'aria-disabled',
                'true'
            )

            fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '31' } })
            fireEvent.click(screen.getByText('Save'))

            await waitFor(() => expect(update).toHaveBeenLastCalledWith('2', { auto_resolve_after_days: 31 }))
            await waitFor(() =>
                expect(container.querySelector('[data-attr="error-tracking-auto-resolve-save"]')).toHaveAttribute(
                    'aria-disabled',
                    'true'
                )
            )
        }
    )
})
