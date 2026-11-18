import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import {
    errorTrackingSettingsRetrieveSettingsRetrieve,
    errorTrackingSettingsUpdateSettingsPartialUpdate,
} from '../../../generated/api'
import { AIFeaturesSettings } from './AIFeaturesSettings'

jest.mock('../../../generated/api', () => ({
    errorTrackingSettingsRetrieveSettingsRetrieve: jest.fn(),
    errorTrackingSettingsUpdateSettingsPartialUpdate: jest.fn(),
}))

const mockRetrieveSettings = jest.mocked(errorTrackingSettingsRetrieveSettingsRetrieve)
const mockUpdateSettings = jest.mocked(errorTrackingSettingsUpdateSettingsPartialUpdate)

describe('AIFeaturesSettings', () => {
    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: { [AccessControlResourceType.ErrorTracking]: AccessControlLevel.Editor },
        } as AppContext
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    test.each([
        { approved: true, enabled: false, disabled: false },
        { approved: false, enabled: false, disabled: true },
        { approved: false, enabled: true, disabled: false },
    ])(
        'AI approval $approved with summaries $enabled disables the switch: $disabled',
        async ({ approved, enabled, disabled }) => {
            initKeaTests(true, undefined, undefined, {
                ...MOCK_DEFAULT_ORGANIZATION,
                is_ai_data_processing_approved: approved,
            })
            mockRetrieveSettings.mockResolvedValue({ ai_issue_summaries_enabled: enabled })

            const { container } = render(<AIFeaturesSettings />)
            const toggle = (): HTMLButtonElement | null =>
                container.querySelector<HTMLButtonElement>('[data-attr="error-tracking-ai-issue-summaries-switch"]')

            await waitFor(() => expect(toggle()?.getAttribute('aria-checked')).toBe(String(enabled)))
            expect(toggle()?.disabled).toBe(disabled)
        }
    )

    test.each([
        {
            name: 'an API error shows its detail once',
            error: { status: 400, detail: 'Your organization must approve AI data processing first.' },
            toast: 'Your organization must approve AI data processing first.',
        },
        {
            name: 'a network error without a status still shows a toast',
            error: new Error('Failed to fetch'),
            toast: "Couldn't save this setting. Check your connection and try again.",
        },
    ])('a failed save: $name', async ({ error, toast }) => {
        initKeaTests(true, undefined, undefined, { ...MOCK_DEFAULT_ORGANIZATION, is_ai_data_processing_approved: true })
        mockRetrieveSettings.mockResolvedValue({ ai_issue_summaries_enabled: false })
        mockUpdateSettings.mockRejectedValue(error)
        const toastError = jest.spyOn(lemonToast, 'error')

        const { container } = render(<AIFeaturesSettings />)
        const toggle = (): HTMLButtonElement | null =>
            container.querySelector<HTMLButtonElement>('[data-attr="error-tracking-ai-issue-summaries-switch"]')
        await waitFor(() => expect(toggle()?.getAttribute('aria-checked')).toBe('false'))

        fireEvent.click(toggle()!)

        await waitFor(() => expect(toastError).toHaveBeenCalled())
        expect(toastError).toHaveBeenCalledTimes(1)
        expect(toastError.mock.calls[0][0]).toBe(toast)
        expect(toggle()?.getAttribute('aria-checked')).toBe('false')
    })
})
