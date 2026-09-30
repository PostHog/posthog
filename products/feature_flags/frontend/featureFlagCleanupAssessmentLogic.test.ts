import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAG_CLEANUP_SKILL } from 'scenes/feature-flags/featureFlagAiContext'
import { MAX_SIDE_PANEL_ID } from 'scenes/max/components/PhaiSidePanelChat'
import { maxMocks } from 'scenes/max/testUtils'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
    AccessControlLevel,
    FeatureFlagBucketingIdentifier,
    FeatureFlagEvaluationRuntime,
    FeatureFlagType,
    SidePanelTab,
} from '~/types'

import { attachedContextLogic, composerSeedLogic, runnerPanelLogic } from 'products/posthog_ai/frontend/api/logics'

import { featureFlagCleanupAssessmentLogic } from './featureFlagCleanupAssessmentLogic'

jest.mock('posthog-js')

const FLAG_ID = 1
const PROJECT_ID = 42

const FEATURE_FLAG: FeatureFlagType & { id: number } = {
    id: FLAG_ID,
    key: 'stale-flag',
    name: '',
    created_at: '2021-01-01',
    updated_at: '2021-01-01',
    created_by: null,
    is_remote_configuration: false,
    filters: { groups: [], payloads: {}, multivariate: null },
    deleted: false,
    archived: false,
    active: true,
    experiment_set: null,
    experiment_set_metadata: null,
    features: null,
    surveys: null,
    can_edit: true,
    tags: [],
    ensure_experience_continuity: null,
    user_access_level: AccessControlLevel.Admin,
    status: 'ACTIVE',
    has_encrypted_payloads: false,
    version: 0,
    last_modified_by: null,
    evaluation_runtime: FeatureFlagEvaluationRuntime.ALL,
    evaluation_contexts: [],
    bucketing_identifier: FeatureFlagBucketingIdentifier.DISTINCT_ID,
}

function setCleanupAvailable(available: boolean): void {
    featureFlagLogic.actions.setFeatureFlags(
        available ? [FEATURE_FLAGS.PHAI_SANDBOX_MODE, FEATURE_FLAGS.FEATURE_FLAG_CLEANUP_ASSESSMENT] : [],
        available
            ? { [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true, [FEATURE_FLAGS.FEATURE_FLAG_CLEANUP_ASSESSMENT]: true }
            : {}
    )
}

describe('featureFlagCleanupAssessmentLogic', () => {
    let logic: ReturnType<typeof featureFlagCleanupAssessmentLogic.build>

    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
        sidePanelStateLogic.mount()
        sidePanelStateLogic.actions.setSidePanelAvailable(true)
        attachedContextLogic.mount()
        // The side panel holds the seed store mounted while the runner chunk loads, so a pending seed can
        // outlive this logic. Mounting it here models that.
        composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).mount()
        logic = featureFlagCleanupAssessmentLogic({ id: FLAG_ID })
        logic.mount()
        ;(posthog.capture as jest.Mock).mockClear()
    })

    afterEach(() => {
        setCleanupAvailable(false)
        logic?.unmount()
        attachedContextLogic.unmount()
        composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).unmount()
    })

    it('is unavailable on the legacy view even when the release flag is on', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.FEATURE_FLAG_CLEANUP_ASSESSMENT], {
            [FEATURE_FLAGS.FEATURE_FLAG_CLEANUP_ASSESSMENT]: true,
        })

        await expectLogic(logic).toMatchValues({ isCleanupAvailable: false })
    })

    it('is unavailable when the release flag is off, even on the new sandbox view', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PHAI_SANDBOX_MODE], {
            [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true,
        })

        await expectLogic(logic).toMatchValues({ isCleanupAvailable: false })
    })

    it('is unavailable on a self-hosted instance with no Anthropic key configured', async () => {
        preflightLogic.actions.loadPreflightSuccess({
            cloud: false,
            is_debug: false,
            anthropic_available: false,
        } as any)
        setCleanupAvailable(true)

        await expectLogic(logic).toMatchValues({ isCleanupAvailable: false })
    })

    it('does nothing when started while unavailable', async () => {
        await expectLogic(logic, () => {
            logic.actions.startAssessment(FEATURE_FLAG.key, PROJECT_ID)
        }).toFinishAllListeners()

        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
        expect(composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).values.seed).toBeNull()
    })

    describe('when available', () => {
        beforeEach(() => {
            setCleanupAvailable(true)
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
                await expectLogic(logic, () => {
                    logic.actions.startAssessment(FEATURE_FLAG.key, PROJECT_ID)
                }).toFinishAllListeners()

                expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)
                expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
                expect(composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).values.seed).toMatchObject({
                    prompt: 'Assess this feature flag for cleanup.',
                    autoSubmit,
                })
            }
        )

        it('carries the cleanup skill and saved flag identity only in the request seed', async () => {
            await expectLogic(logic, () => {
                logic.actions.startAssessment(FEATURE_FLAG.key, PROJECT_ID)
            }).toFinishAllListeners()

            const items = composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).values.seed?.contextItems ?? []
            expect(items).toContainEqual(expect.objectContaining({ type: 'skill', key: FEATURE_FLAG_CLEANUP_SKILL }))
            const target = items.find((item) => item.type === 'feature_flag_cleanup_target')
            expect(JSON.parse(target?.value ?? '')).toEqual({ project_id: PROJECT_ID, id: FLAG_ID, key: 'stale-flag' })
            expect(items).toContainEqual(expect.objectContaining({ type: 'instructions' }))
            expect(attachedContextLogic.values.contextItems).toHaveLength(0)
        })

        it('does not resume whatever the panel was already showing', async () => {
            runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID }).actions.setActiveCreation({ streamKey: 'unrelated-run' })
            runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID }).actions.setHistoryExpanded(true)

            await expectLogic(logic, () => {
                logic.actions.startAssessment(FEATURE_FLAG.key, PROJECT_ID)
            }).toFinishAllListeners()

            expect(runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID }).values.activeCreation).toBeNull()
            expect(runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID }).values.historyExpanded).toBe(false)
        })

        it('ignores a repeat click instead of starting a second assessment', async () => {
            await expectLogic(logic, () => {
                logic.actions.startAssessment(FEATURE_FLAG.key, PROJECT_ID)
                logic.actions.startAssessment(FEATURE_FLAG.key, PROJECT_ID)
            }).toFinishAllListeners()

            // Filtered rather than a raw call count: opening the side panel fires its own "sidebar
            // opened" capture, so the total call count is not specific to this action.
            const clicks = (posthog.capture as jest.Mock).mock.calls.filter(
                ([event]) => event === 'feature flag stale banner review cleanup with ai clicked'
            )
            expect(clicks).toHaveLength(1)
        })

        it('cancels its pending seed on unmount so it cannot reach a later conversation', async () => {
            await expectLogic(logic, () => {
                logic.actions.startAssessment(FEATURE_FLAG.key, PROJECT_ID)
            }).toFinishAllListeners()
            expect(composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).values.seed).not.toBeNull()

            logic.unmount()

            expect(composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).values.seed).toBeNull()
        })

        it.each([
            { leave: 'close', action: () => sidePanelStateLogic.actions.closeSidePanel() },
            { leave: 'switch tabs', action: () => sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Support) },
        ])('cancels a pending seed and allows another assessment after $leave', async ({ action }) => {
            await expectLogic(logic, () => {
                logic.actions.startAssessment(FEATURE_FLAG.key, PROJECT_ID)
            }).toFinishAllListeners()

            action()

            expect(composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).values.seed).toBeNull()
            expect(logic.values.assessmentStarted).toBe(false)

            await expectLogic(logic, () => {
                logic.actions.startAssessment(FEATURE_FLAG.key, PROJECT_ID)
            }).toFinishAllListeners()
            expect(composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).values.seed).not.toBeNull()
        })

        it("leaves another producer's newer seed in place on unmount", async () => {
            await expectLogic(logic, () => {
                logic.actions.startAssessment(FEATURE_FLAG.key, PROJECT_ID)
            }).toFinishAllListeners()
            const otherSeed = { prompt: 'Something else', autoSubmit: false }
            composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).actions.setSeed(otherSeed)

            logic.unmount()

            expect(composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }).values.seed).toEqual(otherSeed)
        })
    })
})
