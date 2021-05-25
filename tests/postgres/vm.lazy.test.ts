import { mocked } from 'ts-jest/utils'

import { PluginLogEntrySource, PluginLogEntryType, PluginTaskType } from '../../src/types'
import { clearError, processError } from '../../src/utils/db/error'
import { status } from '../../src/utils/status'
import { LazyPluginVM } from '../../src/worker/vm/lazy'
import { createPluginConfigVM } from '../../src/worker/vm/vm'
import { plugin60 } from '../helpers/plugins'
import { disablePlugin } from '../helpers/sqlMock'

jest.mock('../../src/worker/vm/vm')
jest.mock('../../src/utils/db/error')
jest.mock('../../src/utils/status')
jest.mock('../../src/utils/db/sql')

const mockConfig = {
    plugin_id: 60,
    team_id: 2,
    id: 39,
    plugin: { ...plugin60 },
}

describe('LazyPluginVM', () => {
    const createVM = () => new LazyPluginVM()
    const mockServer: any = {
        db: {
            createPluginLogEntry: jest.fn(),
        },
    }
    const initializeVm = (vm: LazyPluginVM) => vm.initialize!(mockServer, mockConfig as any, '', 'some plugin')

    describe('VM creation succeeds', () => {
        const mockVM = {
            vm: 'vm',
            methods: {
                processEvent: 'processEvent',
            },
            tasks: {
                schedule: {
                    runEveryMinute: 'runEveryMinute',
                },
            },
        }

        beforeEach(() => {
            mocked(createPluginConfigVM).mockResolvedValue(mockVM as any)
        })

        it('returns correct values for get methods', async () => {
            const vm = createVM()
            void initializeVm(vm)

            expect(await vm.getProcessEvent()).toEqual('processEvent')
            expect(await vm.getProcessEventBatch()).toEqual(null)
            expect(await vm.getTask('someTask', PluginTaskType.Schedule)).toEqual(null)
            expect(await vm.getTask('runEveryMinute', PluginTaskType.Schedule)).toEqual('runEveryMinute')
            expect(await vm.getTasks(PluginTaskType.Schedule)).toEqual(mockVM.tasks.schedule)
        })

        it('logs info and clears errors on success', async () => {
            const vm = createVM()
            void initializeVm(vm)
            await vm.resolveInternalVm

            expect(status.info).toHaveBeenCalledWith('🔌', 'Loaded some plugin')
            expect(clearError).toHaveBeenCalledWith(mockServer, mockConfig)
            expect(mockServer.db.createPluginLogEntry).toHaveBeenCalledWith(
                mockConfig,
                PluginLogEntrySource.System,
                PluginLogEntryType.Info,
                expect.stringContaining('Plugin loaded'),
                undefined
            )
        })
    })

    describe('VM creation fails', () => {
        const error = new Error()

        beforeEach(() => {
            mocked(createPluginConfigVM).mockRejectedValue(error)
        })

        it('returns empty values for get methods', async () => {
            const vm = createVM()
            void initializeVm(vm)

            expect(await vm.getProcessEvent()).toEqual(null)
            expect(await vm.getProcessEventBatch()).toEqual(null)
            expect(await vm.getTask('runEveryMinute', PluginTaskType.Schedule)).toEqual(null)
            expect(await vm.getTasks(PluginTaskType.Schedule)).toEqual({})
        })

        it('logs failure and disables plugin', async () => {
            try {
                const vm = createVM()
                void initializeVm(vm)
                await vm.resolveInternalVm
            } catch {}

            expect(status.warn).toHaveBeenCalledWith('⚠️', 'Failed to load some plugin')
            expect(processError).toHaveBeenCalledWith(mockServer, mockConfig, error)
            expect(disablePlugin).toHaveBeenCalledWith(mockServer, 39)
            expect(mockServer.db.createPluginLogEntry).toHaveBeenCalledWith(
                mockConfig,
                PluginLogEntrySource.System,
                PluginLogEntryType.Error,
                expect.stringContaining('Plugin failed to load'),
                undefined
            )
        })
    })
})
