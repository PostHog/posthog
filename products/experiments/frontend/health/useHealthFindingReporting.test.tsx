import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'

import { dayjs } from 'lib/dayjs'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { ExperimentWarningBanner } from 'scenes/experiments/ExperimentView/ExperimentWarningBanners'
import { Exposures } from 'scenes/experiments/ExperimentView/Exposures'
import { MultiVariantBiasWarning } from 'scenes/experiments/ExperimentView/MultiVariantBiasWarning'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Experiment, ExperimentStatus } from '~/types'

import { NEW_EXPERIMENT } from '../constants'

const EXPERIMENT_ID = 7

describe('useHealthFindingReporting', () => {
    let logic: ReturnType<typeof experimentLogic.build>
    let reportShown: jest.SpyInstance
    let reportActedOn: jest.SpyInstance

    // A running experiment whose flag is off, so the flag-state banner renders with its flag link.
    const renderWarnings = (exposures: Record<string, unknown>): void => {
        logic.actions.setExperiment({
            ...NEW_EXPERIMENT,
            id: EXPERIMENT_ID,
            status: ExperimentStatus.Running,
            start_date: dayjs().subtract(3, 'day').toISOString(),
            feature_flag: { id: 1, key: 'checkout-flag', active: false, filters: { groups: [] } },
        } as unknown as Experiment)
        logic.actions.loadExposuresSuccess(exposures)
        render(
            <Provider>
                <BindLogic logic={experimentLogic} props={{ experimentId: EXPERIMENT_ID }}>
                    <ExperimentWarningBanner />
                    <Exposures />
                    <MultiVariantBiasWarning />
                </BindLogic>
            </Provider>
        )
    }

    beforeEach(() => {
        const emptyList = { count: 0, next: null, previous: null, results: [] }
        useMocks({
            get: {
                '/api/projects/:team/experiments': emptyList,
                '/api/projects/:team/experiment_holdouts': emptyList,
                '/api/projects/:team/experiment_saved_metrics': emptyList,
            },
        })
        initKeaTests()
        logic = experimentLogic({ experimentId: EXPERIMENT_ID })
        logic.mount()
        reportShown = jest.spyOn(logic.actions, 'reportHealthFindingShown')
        reportActedOn = jest.spyOn(logic.actions, 'reportHealthFindingActedOn')
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it.each([
        { actionKind: 'adjust_distribution', control: 'Adjust distribution', code: 'bias_risk_multiple_excluded' },
        {
            actionKind: 'use_first_seen_variant',
            control: 'Use first seen variant',
            code: 'bias_risk_multiple_excluded',
        },
        { actionKind: 'open_feature_flag', control: 'checkout-flag', code: 'flag_off_while_running' },
    ])('reports $actionKind when a person uses that action of a warning', async ({ actionKind, control, code }) => {
        renderWarnings({ timeseries: [], total_exposures: {}, bias_risk: { multiple_variant_percentage: 5 } })

        await userEvent.click(screen.getByText(control))

        expect(reportActedOn).toHaveBeenCalledWith(expect.objectContaining({ code }), actionKind)
    })

    it('reports zero exposures and its action only from the open panel', async () => {
        renderWarnings({ timeseries: [], total_exposures: {} })
        expect(reportShown).not.toHaveBeenCalledWith({ code: 'zero_exposures' })

        await userEvent.click(screen.getByText('Exposures'))
        expect(reportShown).toHaveBeenCalledWith({ code: 'zero_exposures' })

        await userEvent.click(screen.getByText('Edit exposure criteria'))
        expect(reportActedOn).toHaveBeenCalledWith({ code: 'zero_exposures' }, 'edit_exposure_criteria')
    })
})
