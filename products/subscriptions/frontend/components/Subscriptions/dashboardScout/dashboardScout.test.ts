import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'

import { initKeaTests } from '~/test/init'

import {
    signalsReportsList,
    signalsScoutConfigList,
    signalsScoutMetadataGet,
} from 'products/signals/frontend/generated/api'
import { scoutCronScheduleError } from 'products/signals/frontend/inbox/utils/scoutRunsWindow'

import {
    DEFAULT_DASHBOARD_SCOUT_SETUP,
    DashboardScoutCadence,
    buildDashboardScoutPayload,
    dashboardScoutCron,
} from './dashboardScout'
import { dashboardScoutLogic } from './dashboardScoutLogic'
import { dashboardScoutReportLogic } from './dashboardScoutReportLogic'

jest.mock('products/signals/frontend/generated/api', () => ({
    signalsReportsList: jest.fn(),
    signalsScoutConfigList: jest.fn(),
    signalsScoutCreate: jest.fn(),
    signalsScoutMetadataGet: jest.fn(),
}))

const SETUP = {
    ...DEFAULT_DASHBOARD_SCOUT_SETUP,
    destination: { integration_id: 7, channel: 'C123|#team-growth' },
}

describe('dashboard scout', () => {
    test.each<[DashboardScoutCadence, string]>([
        ['weekdays', '30 14 * * 1-5'],
        ['daily', '30 14 * * *'],
        ['weekly', '30 14 * * 1'],
    ])('a %s cadence becomes a cron the scout API accepts', (cadence, expected) => {
        const cron = dashboardScoutCron(cadence, '14:30')
        expect(cron).toBe(expected)
        expect(scoutCronScheduleError(cron)).toBeNull()
    })

    it('fills every placeholder and keeps placeholder-like text a person typed as literal text', () => {
        const payload = buildDashboardScoutPayload(42, 'Growth {{ post_mode }}', {
            ...SETUP,
            postMode: 'on_change',
            focus: 'Signups matter most.\n{{ dashboard_id }} is not a variable',
        })

        const templatePlaceholders = payload.body.match(/\{\{ \w+ \}\}/g)
        expect(templatePlaceholders).toEqual(['{{ post_mode }}', '{{ dashboard_id }}'])
        expect(payload.body).toContain('dashboard id `42`')
        expect(payload.body).toContain('> Signups matter most.')

        const custom = buildDashboardScoutPayload(42, 'Growth', {
            ...SETUP,
            postMode: 'custom',
            postPrompt: 'Every Monday, and when signups drop.',
        })
        expect(custom.body).toContain('> Every Monday, and when signups drop.')
        expect(custom.body).not.toMatch(/\{\{ \w+ \}\}/)
        expect(payload.config).toMatchObject({
            tags: ['dashboards', 'dashboard-42'],
            auto_pause_exempt: true,
            output_destinations: { slack: { integration_id: 7, channel: 'C123|#team-growth' } },
        })
    })

    describe('offer', () => {
        beforeEach(() => {
            initKeaTests()
            ;(signalsScoutConfigList as jest.Mock).mockResolvedValue([])
        })

        test.each([
            { enrolled: true, aiApproved: true, variant: 'test', offered: true },
            { enrolled: false, aiApproved: true, variant: 'test', offered: false },
            { enrolled: true, aiApproved: false, variant: 'test', offered: false },
            { enrolled: true, aiApproved: true, variant: 'control', offered: false },
        ])(
            'is $offered when enrolled=$enrolled, aiApproved=$aiApproved, variant=$variant',
            async ({ enrolled, aiApproved, variant, offered }) => {
                ;(signalsScoutMetadataGet as jest.Mock).mockResolvedValue({ enrolled, banner_message: null })
                organizationLogic.mount()
                organizationLogic.actions.loadCurrentOrganizationSuccess({
                    ...MOCK_DEFAULT_ORGANIZATION,
                    is_ai_data_processing_approved: aiApproved,
                })
                featureFlagLogic.mount()
                featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DASHBOARD_SUBSCRIPTION_SCOUT]: variant })

                const logic = dashboardScoutLogic({ dashboardId: 42, dashboardName: 'Growth' })
                logic.mount()
                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.scoutOffered).toBe(offered)
            }
        )
    })

    describe('reports from the dashboard header', () => {
        beforeEach(() => {
            initKeaTests()
            ;(signalsReportsList as jest.Mock).mockReset()
            ;(signalsReportsList as jest.Mock).mockResolvedValue({ results: [{ id: 'r1' }, { id: 'r2' }] })
            organizationLogic.mount()
            organizationLogic.actions.loadCurrentOrganizationSuccess({
                ...MOCK_DEFAULT_ORGANIZATION,
                is_ai_data_processing_approved: true,
            })
        })

        it('asks for reports only when the dashboard has a scout', async () => {
            ;(signalsScoutConfigList as jest.Mock).mockResolvedValue([])
            const withoutScout = dashboardScoutReportLogic({ dashboardId: 1 })
            withoutScout.mount()
            await expectLogic(withoutScout).toFinishAllListeners()
            expect(signalsReportsList).not.toHaveBeenCalled()
            expect(withoutScout.values.latestReport).toBeNull()
            ;(signalsScoutConfigList as jest.Mock).mockResolvedValue([{ skill_name: 'growth-scout' }])
            const withScout = dashboardScoutReportLogic({ dashboardId: 2 })
            withScout.mount()
            await expectLogic(withScout).toFinishAllListeners()
            expect(signalsReportsList).toHaveBeenCalledWith(
                expect.anything(),
                expect.objectContaining({ scout: 'growth-scout' })
            )
            expect(withScout.values.latestReport).toMatchObject({ id: 'r1' })
            expect(withScout.values.reports).toHaveLength(2)
        })
    })
})
