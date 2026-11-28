import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import {
    errorTrackingSettingsRetrieveSettingsRetrieve,
    errorTrackingSettingsUpdateSettingsPartialUpdate,
} from '../../../generated/api'
import { AutoResolveSettings } from './AutoResolveSettings'

jest.mock('../../../generated/api', () => ({
    errorTrackingSettingsRetrieveSettingsRetrieve: jest.fn(),
    errorTrackingSettingsUpdateSettingsPartialUpdate: jest.fn(),
}))

const mockRetrieveSettings = jest.mocked(errorTrackingSettingsRetrieveSettingsRetrieve)
const mockUpdateSettings = jest.mocked(errorTrackingSettingsUpdateSettingsPartialUpdate)

function getDaysInput(): HTMLElement {
    return screen.getByTestId('error-tracking-auto-resolve-days')
}

function getSaveButton(): HTMLElement {
    return screen.getByTestId('error-tracking-auto-resolve-save')
}

describe('AutoResolveSettings', () => {
    beforeEach(() => {
        mockRetrieveSettings.mockReset()
        mockUpdateSettings.mockReset()
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: { [AccessControlResourceType.ErrorTracking]: AccessControlLevel.Editor },
        } as AppContext
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TODAY_RAIL_NAV]: false })
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: 11 })
    })

    afterEach(cleanup)

    test.each([
        { quill: false, savedDays: null },
        { quill: true, savedDays: 14 },
    ])('validates and saves the threshold (Quill: $quill)', async ({ quill, savedDays }) => {
        featureFlagLogic.actions.setFeatureFlags(quill ? [FEATURE_FLAGS.TODAY_RAIL_NAV] : [], {
            [FEATURE_FLAGS.TODAY_RAIL_NAV]: quill,
        })
        mockRetrieveSettings.mockResolvedValue({ auto_resolve_after_days: savedDays })
        mockUpdateSettings.mockResolvedValue({ auto_resolve_after_days: 21 })
        render(<AutoResolveSettings />)

        const toggle = await screen.findByTestId('error-tracking-auto-resolve-toggle')
        expect(getSaveButton().hasAttribute('data-quill')).toBe(quill)
        expect(toggle).toHaveAttribute('aria-checked', String(savedDays !== null))
        if (savedDays === null) {
            fireEvent.click(toggle)
        }
        fireEvent.change(getDaysInput(), { target: { value: '1.5' } })
        fireEvent.click(getSaveButton())
        expect(await screen.findByText('Enter a whole number of days from 1 to 365')).toBeInTheDocument()
        expect(mockUpdateSettings).not.toHaveBeenCalled()

        fireEvent.change(getDaysInput(), { target: { value: '21' } })
        fireEvent.click(getSaveButton())
        await waitFor(() => expect(getDaysInput()).not.toBeDisabled())
        expect(getSaveButton()).toHaveAttribute('aria-disabled', 'true')
        expect(mockUpdateSettings).toHaveBeenCalledTimes(1)
        expect(mockUpdateSettings).toHaveBeenCalledWith('11', { auto_resolve_after_days: 21 })
    })

    test('sends null when the user saves after turning auto-resolve off', async () => {
        mockRetrieveSettings.mockResolvedValue({ auto_resolve_after_days: 21 })
        mockUpdateSettings.mockResolvedValue({ auto_resolve_after_days: null })
        render(<AutoResolveSettings />)

        const toggle = await screen.findByTestId('error-tracking-auto-resolve-toggle')
        expect(toggle).toBeChecked()
        fireEvent.click(toggle)
        expect(mockUpdateSettings).not.toHaveBeenCalled()

        fireEvent.click(getSaveButton())
        await waitFor(() => expect(toggle).not.toBeDisabled())
        expect(getSaveButton()).toHaveAttribute('aria-disabled', 'true')
        expect(mockUpdateSettings).toHaveBeenCalledTimes(1)
        expect(mockUpdateSettings).toHaveBeenCalledWith('11', { auto_resolve_after_days: null })
        expect(toggle).not.toBeChecked()
    })

    test('does not carry a draft to another project or show a save control after a failed load', async () => {
        mockRetrieveSettings
            .mockResolvedValueOnce({ auto_resolve_after_days: 21 })
            .mockRejectedValueOnce(new Error('Could not load settings'))
        render(<AutoResolveSettings />)

        await screen.findByTestId('error-tracking-auto-resolve-days')
        fireEvent.change(getDaysInput(), { target: { value: '42' } })
        expect(getSaveButton()).toHaveAttribute('aria-disabled', 'false')

        act(() => teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: 12 }))
        expect(screen.queryByTestId('error-tracking-auto-resolve-save')).not.toBeInTheDocument()
        expect(await screen.findByText(/couldn't load auto-resolve settings/i)).toBeInTheDocument()
        expect(screen.queryByTestId('error-tracking-auto-resolve-toggle')).not.toBeInTheDocument()
        expect(mockRetrieveSettings).toHaveBeenLastCalledWith('12')
        expect(mockUpdateSettings).not.toHaveBeenCalled()
    })
})
