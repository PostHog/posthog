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
// Another editor changed the stats config while this user edited it, which is what makes the server reject the save.
const serverExperiment = {
    ...savedExperiment,
    version: 2,
    stats_config: { method: ExperimentStatsMethod.Bayesian, bayesian: { ci_level: 0.9 } },
} as Experiment

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

const echoSave = async ({ request }: { request: Request }): Promise<[number, Experiment]> => [
    200,
    { ...savedExperiment, ...(await request.json()) },
]

const RESPONSES = {
    fails: () => [400, { type: 'validation_error', code: 'invalid_input', detail: 'Invalid stats config', attr: null }],
    conflicts: () => [
        409,
        { type: 'validation_error', code: 'conflict', detail: 'Changed elsewhere', current_version: 2 },
    ],
    succeeds: echoSave,
}

describe('stats config modals', () => {
    let logic: ReturnType<typeof experimentLogic.build>

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    function renderModalWithEdit(modal: keyof typeof MODALS): void {
        const { Modal, open, edit } = MODALS[modal]
        initKeaTests()
        logic = experimentLogic({ experimentId: EXPERIMENT_ID })
        logic.mount()
        logic.actions.setUnmodifiedExperiment(savedExperiment)
        logic.actions.setExperiment(savedExperiment)
        open()
        render(
            <Provider>
                <BindLogic logic={experimentLogic} props={{ experimentId: EXPERIMENT_ID }}>
                    <Modal />
                </BindLogic>
            </Provider>
        )
        // The modal options write the edit into the local experiment, as this does.
        act(() => logic.actions.setExperiment({ stats_config: edit }))
    }

    it.each([
        { modal: 'CUPED', outcome: 'fails', open: true, shows: 'edited' },
        { modal: 'stats', outcome: 'fails', open: true, shows: 'edited' },
        { modal: 'CUPED', outcome: 'conflicts', open: true, shows: 'server' },
        { modal: 'stats', outcome: 'conflicts', open: true, shows: 'server' },
        { modal: 'CUPED', outcome: 'succeeds', open: false, shows: 'edited' },
        { modal: 'stats', outcome: 'succeeds', open: false, shows: 'edited' },
    ] as const)(
        'when the save $outcome, the $modal modal is open: $open, with the $shows settings',
        async ({ modal, outcome, open, shows }) => {
            const { isOpen, edit } = MODALS[modal]
            useMocks({
                get: { '/api/projects/:team/experiments/:id': serverExperiment },
                patch: { '/api/projects/:team/experiments/:id': RESPONSES[outcome] },
            })
            renderModalWithEdit(modal)

            fireEvent.click(screen.getByText('Save'))
            await act(() => expectLogic(logic).toFinishAllListeners())

            expect(isOpen()).toBe(open)
            // After a conflict, Save must send the other editor's change, so the modal shows the server's settings.
            expect(logic.values.experiment.stats_config).toEqual(
                shows === 'edited' ? edit : serverExperiment.stats_config
            )
            expect(lemonToast.success).toHaveBeenCalledTimes(open ? 0 : 1)
            expect(lemonToast.error).toHaveBeenCalledTimes(open ? 1 : 0)
        }
    )

    it.each(['CUPED', 'stats'] as const)('the %s modal does not cancel while its save runs', async (modal) => {
        const { isOpen, edit } = MODALS[modal]
        let finishSave = (): void => {}
        const saveFinished = new Promise<void>((resolve) => {
            finishSave = resolve
        })
        useMocks({
            patch: {
                '/api/projects/:team/experiments/:id': async (request: { request: Request }) => {
                    await saveFinished
                    return echoSave(request)
                },
            },
        })
        renderModalWithEdit(modal)

        fireEvent.click(screen.getByText('Save'))
        fireEvent.click(screen.getByText('Cancel'))

        expect(isOpen()).toBe(true)
        expect(logic.values.experiment.stats_config).toEqual(edit)

        finishSave()
        await act(() => expectLogic(logic).toFinishAllListeners())

        expect(isOpen()).toBe(false)
        expect(logic.values.experiment.stats_config).toEqual(edit)
    })
})
