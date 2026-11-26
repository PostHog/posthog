import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { LemonDialog } from '@posthog/lemon-ui'

import { initKeaTests } from '~/test/init'

import { signalsScoutConfigDestroy, signalsScoutConfigList } from 'products/signals/frontend/generated/api'
import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'
import { llmSkillsNameArchiveCreate } from 'products/skills/frontend/generated/api'

import { scoutDetailActionsLogic } from './scoutDetailActionsLogic'
import { scoutFleetLogic } from './scoutFleetLogic'

jest.mock('posthog-js')
jest.mock('products/signals/frontend/generated/api', () => ({
    signalsScoutConfigDestroy: jest.fn(),
    signalsScoutConfigList: jest.fn(),
    signalsScoutConfigSync: jest.fn(),
    signalsScoutNotesList: jest.fn().mockResolvedValue({ results: [] }),
    signalsScoutRunsRecentPerScout: jest.fn(),
}))
jest.mock('products/skills/frontend/generated/api', () => ({
    llmSkillsNameArchiveCreate: jest.fn(),
}))

const mockDestroy = signalsScoutConfigDestroy as jest.MockedFunction<typeof signalsScoutConfigDestroy>
const mockList = signalsScoutConfigList as jest.MockedFunction<typeof signalsScoutConfigList>
const mockArchive = llmSkillsNameArchiveCreate as jest.MockedFunction<typeof llmSkillsNameArchiveCreate>

const CUSTOM_CONFIG = {
    id: 'config-1',
    skill_name: 'signals-scout-custom-checkout',
    scout_origin: 'custom',
    owners: [],
    enabled: true,
} as unknown as SignalScoutConfigApi

describe('scoutDetailActionsLogic', () => {
    let fleet: ReturnType<typeof scoutFleetLogic.build>
    let openDialog: jest.SpyInstance

    beforeEach(async () => {
        localStorage.clear()
        initKeaTests()
        mockList.mockReset().mockResolvedValue([])
        mockDestroy.mockReset().mockResolvedValue(undefined)
        mockArchive.mockReset().mockResolvedValue(undefined as any)
        // Confirms at once, as a person clicking Delete in the dialog would.
        openDialog = jest.spyOn(LemonDialog, 'open').mockImplementation((props) => {
            const onClick = props.primaryButton?.onClick as (() => void) | undefined
            onClick?.()
        })
        fleet = scoutFleetLogic()
        fleet.mount()
        await expectLogic(fleet).toFinishAllListeners()
    })

    afterEach(() => {
        openDialog.mockRestore()
        fleet.unmount()
    })

    function mountFor(config: SignalScoutConfigApi): ReturnType<typeof scoutDetailActionsLogic.build> {
        fleet.actions.loadScoutConfigsSuccess([config])
        const logic = scoutDetailActionsLogic({ skillName: config.skill_name })
        logic.mount()
        return logic
    }

    it('deletes a custom scout from the header and reports the header as the entry point', async () => {
        const logic = mountFor(CUSTOM_CONFIG)
        expect(logic.values.canDelete).toBe(true)

        await expectLogic(logic, () => logic.actions.confirmDelete()).toFinishAllListeners()
        await expectLogic(fleet).toFinishAllListeners()

        expect(fleet.values.scoutConfigs).toEqual([])
        expect(posthog.capture).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({
                action_type: 'delete_scout',
                surface: 'scout_detail',
                entry_point: 'header',
                success: true,
            }),
            undefined
        )
        logic.unmount()
    })

    it('offers no delete for a canonical scout', async () => {
        const logic = mountFor({ ...CUSTOM_CONFIG, scout_origin: 'canonical' } as SignalScoutConfigApi)
        expect(logic.values.canDelete).toBe(false)

        await expectLogic(logic, () => logic.actions.confirmDelete()).toFinishAllListeners()

        expect(fleet.values.scoutConfigs).toHaveLength(1)
        logic.unmount()
    })
})
