import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { settingsLogic } from 'scenes/settings/settingsLogic'

import { ErrorTrackingAIFeatureEnumApi } from '~/generated/core/api.schemas'
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

jest.mock('posthog-js/dist/surveys-preview', () => ({
    renderFeedbackWidgetPreview: jest.fn(),
    renderSurveysPreview: jest.fn(),
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

    test.each([
        { features: [ErrorTrackingAIFeatureEnumApi.IssueSummaries], visible: true },
        { features: [], visible: false },
        { features: undefined, visible: false },
    ])('the settings list the section for a team with AI features $features: $visible', ({ features, visible }) => {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, available_error_tracking_ai_features: features })
        const logic = settingsLogic({
            logicKey: 'ai-features-visibility-test',
            sectionId: 'environment-error-tracking-configuration',
        })
        logic.mount()

        expect(logic.values.settings.some((setting) => setting.id === 'error-tracking-ai-features')).toBe(visible)
    })
})
