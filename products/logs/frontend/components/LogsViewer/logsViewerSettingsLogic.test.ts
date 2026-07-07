import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { initKeaTests } from '~/test/init'

import { logsViewerSettingsLogic } from './logsViewerSettingsLogic'

describe('logsViewerSettingsLogic', () => {
    let logic: ReturnType<typeof logsViewerSettingsLogic.build>

    afterEach(() => {
        logic?.unmount()
    })

    it('seeds the timezone default from the project timezone', async () => {
        localStorage.clear()
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, timezone: 'Asia/Bangkok' })

        logic = logsViewerSettingsLogic()
        logic.mount()

        expect(logic.values.timezone).toBe('Asia/Bangkok')
    })

    it('keeps a manually chosen timezone after it is set', async () => {
        localStorage.clear()
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, timezone: 'Asia/Bangkok' })

        logic = logsViewerSettingsLogic()
        logic.mount()
        logic.actions.setTimezone('America/New_York')

        expect(logic.values.timezone).toBe('America/New_York')
    })
})
