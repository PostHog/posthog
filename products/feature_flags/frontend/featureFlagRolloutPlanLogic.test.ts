import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { FEATURE_FLAG_ROLLOUT_SKILL } from 'scenes/feature-flags/featureFlagAiContext'
import { maxMocks } from 'scenes/max/testUtils'
import { organizationLogic } from 'scenes/organizationLogic'

import { MAX_SIDE_PANEL_ID } from '~/layout/ai/aiPanelIds'
import { runnerPanelLogic } from '~/layout/ai/runnerPanelLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { composerSeedLogic } from 'products/posthog_ai/frontend/api/logics'

import { featureFlagRolloutPlanLogic } from './featureFlagRolloutPlanLogic'

jest.mock('posthog-js')
jest.mock('lib/utils/copyToClipboard', () => ({ copyToClipboard: jest.fn().mockResolvedValue(true) }))

const FLAG_ID = 1
const FLAG_KEY = 'faster-report-cache'
const PROJECT_ID = 42

function setSandboxView(enabled: boolean): void {
    featureFlagLogic.actions.setFeatureFlags(
        enabled ? [FEATURE_FLAGS.PHAI_SANDBOX_MODE] : [],
        enabled ? { [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true } : {}
    )
}

describe('featureFlagRolloutPlanLogic', () => {
    let logic: ReturnType<typeof featureFlagRolloutPlanLogic.build>
    const seed = (): ReturnType<typeof composerSeedLogic.build>['values']['seed'] =>
        composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).values.seed
    const captures = (event: string): unknown[] =>
        (posthog.capture as jest.Mock).mock.calls.filter(([name]) => name === event)

    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
        sidePanelStateLogic.mount()
        sidePanelStateLogic.actions.setSidePanelAvailable(true)
        composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).mount()
        ;(posthog.capture as jest.Mock).mockClear()
        ;(copyToClipboard as jest.Mock).mockClear()
        logic = featureFlagRolloutPlanLogic({ id: FLAG_ID })
        logic.mount()
    })

    afterEach(() => {
        setSandboxView(false)
        logic.unmount()
        composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).unmount()
    })

    it('still offers the copied prompt when the agent sandbox is unavailable', async () => {
        await expectLogic(logic).toMatchValues({ isAiPlanAvailable: false })

        await expectLogic(logic, () => {
            logic.actions.startPlan(FLAG_KEY, PROJECT_ID)
            logic.actions.copyAgentPrompt(FLAG_KEY, PROJECT_ID)
        }).toFinishAllListeners()

        expect(seed()).toBeNull()
        const prompt = (copyToClipboard as jest.Mock).mock.calls[0][0]
        expect(prompt).toContain(FEATURE_FLAG_ROLLOUT_SKILL)
        expect(prompt).toContain(FLAG_KEY)
        expect(prompt).toContain(String(PROJECT_ID))
        expect(captures('feature flag rollout hint shown')).toHaveLength(1)
    })

    it.each([
        { copied: true, events: 1 },
        { copied: false, events: 0 },
    ])('records $events copies when the clipboard write returns $copied', async ({ copied, events }) => {
        ;(copyToClipboard as jest.Mock).mockResolvedValueOnce(copied)

        await expectLogic(logic, () => logic.actions.copyAgentPrompt(FLAG_KEY, PROJECT_ID)).toFinishAllListeners()

        expect(captures('feature flag rollout hint prompt copied')).toHaveLength(events)
    })

    describe('in the agent sandbox', () => {
        beforeEach(() => {
            setSandboxView(true)
        })

        it('seeds the skill and the flag identity, and opens the panel once', async () => {
            await expectLogic(logic, () => {
                logic.actions.startPlan(FLAG_KEY, PROJECT_ID)
                logic.actions.startPlan(FLAG_KEY, PROJECT_ID)
            }).toFinishAllListeners()

            const items = seed()?.contextItems ?? []
            expect(items).toContainEqual(expect.objectContaining({ type: 'skill', key: FEATURE_FLAG_ROLLOUT_SKILL }))
            const target = items.find((item) => item.type === 'feature_flag_rollout_target')
            expect(JSON.parse(target?.value ?? '')).toEqual({ project_id: PROJECT_ID, id: FLAG_ID, key: FLAG_KEY })
            expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
            expect(captures('feature flag rollout hint plan clicked')).toHaveLength(1)
        })

        it.each([
            { approved: true, autoSubmit: true },
            { approved: false, autoSubmit: false },
        ])(
            'sets autoSubmit to $autoSubmit when AI data processing approval is $approved',
            async ({ approved, autoSubmit }) => {
                organizationLogic.actions.loadCurrentOrganizationSuccess({
                    ...MOCK_DEFAULT_ORGANIZATION,
                    is_ai_data_processing_approved: approved,
                })

                await expectLogic(logic, () => logic.actions.startPlan(FLAG_KEY, PROJECT_ID)).toFinishAllListeners()

                expect(seed()).toMatchObject({ autoSubmit })
            }
        )

        it('does not resume whatever the panel was already showing', async () => {
            const runner = runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID })
            runner.actions.setActiveCreation({ streamKey: 'unrelated-run' })
            runner.actions.setHistoryExpanded(true)

            await expectLogic(logic, () => logic.actions.startPlan(FLAG_KEY, PROJECT_ID)).toFinishAllListeners()

            expect(runner.values.activeCreation).toBeNull()
            expect(runner.values.historyExpanded).toBe(false)
        })

        it.each([
            { name: 'drops its own pending seed', otherSeed: null },
            { name: "keeps another producer's newer seed", otherSeed: { prompt: 'Something else', autoSubmit: false } },
        ])('$name on unmount', async ({ otherSeed }) => {
            await expectLogic(logic, () => logic.actions.startPlan(FLAG_KEY, PROJECT_ID)).toFinishAllListeners()
            if (otherSeed) {
                composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).actions.setSeed(otherSeed)
            }

            logic.unmount()

            expect(seed()).toEqual(otherSeed)
        })

        it.each([
            ['the panel closes', () => sidePanelStateLogic.actions.closeSidePanel()],
            ['the panel moves to another tab', () => sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Support)],
        ])('drops the pending plan when %s, so it can start again', async (_name, leave) => {
            await expectLogic(logic, () => logic.actions.startPlan(FLAG_KEY, PROJECT_ID)).toFinishAllListeners()

            await expectLogic(logic, leave).toFinishAllListeners()

            expect(seed()).toBeNull()
            expect(logic.values.planStarted).toBe(false)

            await expectLogic(logic, () => logic.actions.startPlan(FLAG_KEY, PROJECT_ID)).toFinishAllListeners()
            expect(seed()).not.toBeNull()
        })
    })
})
