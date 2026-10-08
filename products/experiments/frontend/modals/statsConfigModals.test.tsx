import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { modalsLogic } from 'scenes/experiments/modalsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Experiment, ExperimentStatsMethod } from '~/types'

import { NEW_EXPERIMENT } from 'products/experiments/frontend/constants'
import { CupedModal } from 'products/experiments/frontend/modals/CupedModal/CupedModal'
import { StatsMethodModal } from 'products/experiments/frontend/modals/StatsMethodModal/StatsMethodModal'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn(), info: jest.fn() },
}))

const EXPERIMENT_ID = 7
const savedExperiment = {
    ...NEW_EXPERIMENT,
    id: EXPERIMENT_ID,
    version: 1,
    stats_config: { method: ExperimentStatsMethod.Bayesian },
} as Experiment
const serverExperiment = { ...savedExperiment, version: 2, name: 'Renamed elsewhere' } as Experiment

const MODALS = {
    CUPED: {
        Modal: CupedModal,
        open: () => modalsLogic.actions.openCupedModal(),
        isOpen: () => modalsLogic.values.isCupedModalOpen,
        edit: { method: ExperimentStatsMethod.Bayesian, cuped: { enabled: true } },
    },
    stats: {
        Modal: StatsMethodModal,
        open: () => modalsLogic.actions.openStatsEngineModal(),
        isOpen: () => modalsLogic.values.isStatsEngineModalOpen,
        edit: { method: ExperimentStatsMethod.Frequentist },
    },
}

const RESPONSES = {
    fails: () => [400, { type: 'validation_error', code: 'invalid_input', detail: 'Invalid stats config', attr: null }],
    conflicts: () => [
        409,
        { type: 'validation_error', code: 'conflict', detail: 'Changed elsewhere', current_version: 2 },
    ],
    succeeds: async ({ request }: { request: Request }) => [200, { ...savedExperiment, ...(await request.json()) }],
}

describe('stats config modals', () => {
    let logic: ReturnType<typeof experimentLogic.build>

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it.each([
        { modal: 'CUPED', outcome: 'fails', open: true },
        { modal: 'stats', outcome: 'fails', open: true },
        { modal: 'CUPED', outcome: 'conflicts', open: true },
        { modal: 'stats', outcome: 'conflicts', open: true },
        { modal: 'CUPED', outcome: 'succeeds', open: false },
        { modal: 'stats', outcome: 'succeeds', open: false },
    ] as const)('when the save $outcome, the $modal modal is open: $open', async ({ modal, outcome, open }) => {
        const { Modal, open: openModal, isOpen, edit } = MODALS[modal]
        useMocks({
            get: { '/api/projects/:team/experiments/:id': serverExperiment },
            patch: { '/api/projects/:team/experiments/:id': RESPONSES[outcome] },
        })
        initKeaTests()
        logic = experimentLogic({ experimentId: EXPERIMENT_ID })
        logic.mount()
        logic.actions.setUnmodifiedExperiment(savedExperiment)
        logic.actions.setExperiment(savedExperiment)
        openModal()
        render(
            <Provider>
                <BindLogic logic={experimentLogic} props={{ experimentId: EXPERIMENT_ID }}>
                    <Modal />
                </BindLogic>
            </Provider>
        )

        // The modal options write the edit into the local experiment, as this does.
        act(() => logic.actions.setExperiment({ stats_config: edit }))
        fireEvent.click(screen.getByText('Save'))
        await act(async () => {
            await expectLogic(logic).toFinishAllListeners()
            // The modal acts on the save outcome after the listeners settle, so drain the microtask queue. waitFor
            // cannot replace this, because an open modal looks the same before and after the outcome.
            await new Promise((resolve) => setTimeout(resolve, 0))
        })

        expect(isOpen()).toBe(open)
        expect(logic.values.experiment.stats_config).toEqual(edit)
        expect(lemonToast.success).toHaveBeenCalledTimes(open ? 0 : 1)
        expect(lemonToast.error).toHaveBeenCalledTimes(open ? 1 : 0)
    })
})
