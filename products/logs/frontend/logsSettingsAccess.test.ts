import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { settingsLogic } from 'scenes/settings/settingsLogic'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

jest.mock('posthog-js/dist/surveys-preview', () => ({
    renderFeedbackWidgetPreview: jest.fn(),
    renderSurveysPreview: jest.fn(),
}))

describe('logs settings access', () => {
    let priorResourceAccess: AppContext['resource_access_control']

    beforeEach(() => {
        initKeaTests()
        priorResourceAccess = window.POSTHOG_APP_CONTEXT!.resource_access_control
    })

    afterEach(() => {
        window.POSTHOG_APP_CONTEXT!.resource_access_control = priorResourceAccess
    })

    it.each([
        [AccessControlLevel.None, false],
        [AccessControlLevel.Viewer, true],
        [AccessControlLevel.Editor, true],
    ])('logs access=%s shows the logs-scoped rule settings: %s', (logsAccess, visible) => {
        window.POSTHOG_APP_CONTEXT!.resource_access_control = {
            [AccessControlResourceType.Logs]: logsAccess,
        } as Record<AccessControlResourceType, AccessControlLevel>
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.METRICS]: true })
        const logic = settingsLogic({ logicKey: 'logs-settings-access-test', sectionId: 'environment-logs' })
        logic.mount()

        const settingIds = logic.values.settings.map(({ id }) => id)
        expect(settingIds).toContain('logs')
        expect(settingIds.includes('logs-drop-rules')).toBe(visible)
        expect(settingIds.includes('logs-metric-rules')).toBe(visible)
        expect(
            logic.values.globalSearchIndex.search('Drop rules').some(({ item }) => item.settingId === 'logs-drop-rules')
        ).toBe(visible)

        logic.unmount()
    })
})
