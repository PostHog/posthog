import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { cleanup, render, waitFor } from '@testing-library/react'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { errorTrackingSettingsRetrieveSettingsRetrieve } from '../../../generated/api'
import { AIFeaturesSettings } from './AIFeaturesSettings'

jest.mock('../../../generated/api', () => ({
    errorTrackingSettingsRetrieveSettingsRetrieve: jest.fn(),
    errorTrackingSettingsUpdateSettingsPartialUpdate: jest.fn(),
}))

const mockRetrieveSettings = jest.mocked(errorTrackingSettingsRetrieveSettingsRetrieve)

describe('AIFeaturesSettings', () => {
    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: { [AccessControlResourceType.ErrorTracking]: AccessControlLevel.Editor },
        } as AppContext
    })

    afterEach(cleanup)

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
})
