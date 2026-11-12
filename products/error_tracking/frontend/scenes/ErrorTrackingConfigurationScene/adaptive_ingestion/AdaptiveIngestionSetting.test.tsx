import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { cleanup, render, waitFor } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { errorTrackingSettingsRetrieveSettingsRetrieve } from '../../../generated/api'
import { AdaptiveIngestionSetting } from './AdaptiveIngestionSetting'

jest.mock('../../../generated/api', () => ({
    errorTrackingSettingsRetrieveSettingsRetrieve: jest.fn(),
}))

const mockRetrieveSettings = jest.mocked(errorTrackingSettingsRetrieveSettingsRetrieve)

describe('AdaptiveIngestionSetting', () => {
    beforeEach(() => {
        initKeaTests()
        teamLogic.mount()
    })

    afterEach(cleanup)

    test.each([true, false])('shows the saved value %s without enabling the switch', async (enabled) => {
        const projectId = enabled ? 11 : 12
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: projectId })
        mockRetrieveSettings.mockResolvedValue({ adaptive_ingestion_enabled: enabled })

        const { container } = render(<AdaptiveIngestionSetting />)

        await waitFor(() =>
            expect(
                container.querySelector('[data-attr="adaptive-ingestion-toggle"]')?.getAttribute('aria-checked')
            ).toBe(String(enabled))
        )
        expect(mockRetrieveSettings).toHaveBeenCalledWith(String(projectId))
        expect(container.querySelector('[data-attr="adaptive-ingestion-toggle"]')?.tagName).toBe('DIV')
    })
})
