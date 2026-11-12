import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import {
    errorTrackingSettingsRetrieveSettingsRetrieve,
    errorTrackingSettingsUpdateSettingsPartialUpdate,
} from '../../../generated/api'
import { AdaptiveIngestionSetting } from './AdaptiveIngestionSetting'

jest.mock('../../../generated/api', () => ({
    errorTrackingSettingsRetrieveSettingsRetrieve: jest.fn(),
    errorTrackingSettingsUpdateSettingsPartialUpdate: jest.fn(),
}))

const mockRetrieveSettings = jest.mocked(errorTrackingSettingsRetrieveSettingsRetrieve)
const mockUpdateSettings = jest.mocked(errorTrackingSettingsUpdateSettingsPartialUpdate)

describe('AdaptiveIngestionSetting', () => {
    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: { [AccessControlResourceType.ErrorTracking]: AccessControlLevel.Editor },
        } as AppContext
        initKeaTests()
        teamLogic.mount()
    })

    afterEach(cleanup)

    test.each([true, false])('shows the saved value %s and saves the opposite on click', async (enabled) => {
        const projectId = enabled ? 11 : 12
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: projectId })
        mockRetrieveSettings.mockResolvedValue({ adaptive_ingestion_enabled: enabled })
        mockUpdateSettings.mockResolvedValue({ adaptive_ingestion_enabled: !enabled })

        const { container } = render(<AdaptiveIngestionSetting />)
        const toggle = (): Element | null => container.querySelector('[data-attr="adaptive-ingestion-toggle"]')

        await waitFor(() => expect(toggle()?.getAttribute('aria-checked')).toBe(String(enabled)))
        expect(mockRetrieveSettings).toHaveBeenCalledWith(String(projectId))

        fireEvent.click(toggle()!)

        await waitFor(() => expect(toggle()?.getAttribute('aria-checked')).toBe(String(!enabled)))
        expect(mockUpdateSettings).toHaveBeenCalledWith(String(projectId), { adaptive_ingestion_enabled: !enabled })
    })
})
