import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import type { LogsSourceApi } from 'products/logs/frontend/generated/api.schemas'

import { logsSourcesLogic } from './logsSourcesLogic'

const mockList = jest.fn()
const mockCreate = jest.fn()
const mockHealth = jest.fn()
const mockSetup = jest.fn()
const mockPartialUpdate = jest.fn()

jest.mock('products/logs/frontend/generated/api', () => ({
    logsSourcesList: (...args: unknown[]) => mockList(...args),
    logsSourcesCreate: (...args: unknown[]) => mockCreate(...args),
    logsSourcesHealthRetrieve: (...args: unknown[]) => mockHealth(...args),
    logsSourcesSetupRetrieve: (...args: unknown[]) => mockSetup(...args),
    logsSourcesPartialUpdate: (...args: unknown[]) => mockPartialUpdate(...args),
}))

const source: LogsSourceApi = {
    id: 'src-1',
    name: 'Production account',
    provider: 'aws_cloudwatch',
    mode: 'push',
    enabled: true,
    config: { region: 'us-east-1', default_labels: {}, service_name_overrides: {} },
    created_by: 1,
    created_at: '2026-09-16T10:00:00Z',
    updated_at: null,
}

describe('logsSourcesLogic', () => {
    let logic: ReturnType<typeof logsSourcesLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockList.mockReset().mockResolvedValue({ count: 0, results: [] })
        mockCreate.mockReset().mockResolvedValue(source)
        mockHealth.mockReset().mockResolvedValue({
            sources: {
                'src-1': { status: 'waiting', last_received_at: null, records_received_24h: 0, records_dropped_24h: 0 },
            },
        })
        mockPartialUpdate.mockReset().mockResolvedValue({ ...source, enabled: false })
        mockSetup.mockReset().mockResolvedValue({
            endpoint_path: '/i/v1/logs/aws/firehose/src-1',
            endpoint_url: 'https://us.i.posthog.com/i/v1/logs/aws/firehose/src-1',
            access_key: 'phc_test',
            buffering_size_mb: 1,
            buffering_interval_seconds: 60,
            retry_duration_seconds: 300,
            content_encoding: 'GZIP',
            quick_create_url: null,
        })
        logic = logsSourcesLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('creating a source moves the wizard to the connect step for that source and loads its setup values', async () => {
        mockList.mockResolvedValue({ count: 1, results: [source] })
        logic.actions.openWizard()
        logic.actions.setDraftName('  Production account ')
        logic.actions.setDraftRegion('us-east-1')

        await expectLogic(logic, () => {
            logic.actions.createSource()
        })
            .toDispatchActionsInAnyOrder(['sourceCreated', 'setWizardStep', 'loadSetupSuccess', 'createSourceFinished'])
            .toMatchValues({ wizardStep: 'connect', wizardSourceId: 'src-1', createPending: false })

        expect(mockCreate).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ name: 'Production account', config: { region: 'us-east-1' } })
        )
        expect(logic.values.setup?.access_key).toEqual('phc_test')
        expect(mockSetup).toHaveBeenCalledWith(expect.any(String), 'src-1')
    })

    it('does not create a source without a name', async () => {
        logic.actions.openWizard()
        logic.actions.setDraftRegion('us-east-1')

        await expectLogic(logic, () => {
            logic.actions.createSource()
        }).toDispatchActions(['createSourceFinished'])

        expect(mockCreate).not.toHaveBeenCalled()
        expect(logic.values.wizardStep).toEqual('details')
    })

    it('loads health only when there are sources to ask about', async () => {
        await expectLogic(logic).toDispatchActions(['loadSourcesSuccess'])
        expect(mockHealth).not.toHaveBeenCalled()

        mockList.mockResolvedValue({ count: 1, results: [source] })
        await expectLogic(logic, () => {
            logic.actions.loadSources()
        }).toDispatchActions(['loadSourcesSuccess', 'loadHealthSuccess'])

        expect(mockHealth).toHaveBeenCalledTimes(1)
        expect(logic.values.healthBySourceId['src-1'].status).toEqual('waiting')
    })

    it('flips a source as soon as the switch is clicked and reloads the list only when the update fails', async () => {
        mockList.mockResolvedValue({ count: 1, results: [source] })
        await expectLogic(logic, () => {
            logic.actions.loadSources()
        }).toDispatchActions(['loadSourcesSuccess'])

        await expectLogic(logic, () => {
            logic.actions.setSourceEnabled('src-1', false)
        })
            .toMatchValues({ sources: [{ ...source, enabled: false }], togglePendingId: 'src-1' })
            .toDispatchActions(['setSourceEnabledFinished'])
            .toMatchValues({ togglePendingId: null })
        expect(mockPartialUpdate).toHaveBeenCalledWith(expect.any(String), 'src-1', { enabled: false })
        expect(mockList).toHaveBeenCalledTimes(2)

        mockPartialUpdate.mockRejectedValue({ detail: 'nope' })
        mockList.mockResolvedValue({ count: 1, results: [{ ...source, enabled: false }] })
        await expectLogic(logic, () => {
            logic.actions.setSourceEnabled('src-1', true)
        }).toDispatchActions(['setSourceEnabledFinished', 'loadSourcesSuccess'])
        expect(logic.values.sources).toEqual([{ ...source, enabled: false }])
    })
})
