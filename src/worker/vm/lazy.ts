import {
    PluginConfig,
    PluginConfigVMReponse,
    PluginLogEntrySource,
    PluginLogEntryType,
    PluginsServer,
    PluginTask,
    PluginTaskType,
} from '../../types'
import { clearError, processError } from '../../utils/db/error'
import { status } from '../../utils/status'
import { createPluginConfigVM } from './vm'

export class LazyPluginVM {
    initialize?: (server: PluginsServer, pluginConfig: PluginConfig, indexJs: string, logInfo: string) => Promise<void>
    failInitialization?: () => void
    resolveInternalVm: Promise<PluginConfigVMReponse | null>

    constructor() {
        this.resolveInternalVm = new Promise((resolve) => {
            this.initialize = async (
                server: PluginsServer,
                pluginConfig: PluginConfig,
                indexJs: string,
                logInfo = ''
            ) => {
                try {
                    const vm = await createPluginConfigVM(server, pluginConfig, indexJs)
                    await server.db.createPluginLogEntry(
                        pluginConfig,
                        PluginLogEntrySource.System,
                        PluginLogEntryType.Info,
                        `Plugin loaded (instance ID ${server.instanceId}).`,
                        server.instanceId
                    )
                    status.info('🔌', `Loaded ${logInfo}`)
                    void clearError(server, pluginConfig)
                    resolve(vm)
                } catch (error) {
                    await server.db.createPluginLogEntry(
                        pluginConfig,
                        PluginLogEntrySource.System,
                        PluginLogEntryType.Error,
                        `Plugin failed to load (instance ID ${server.instanceId}).`,
                        server.instanceId
                    )
                    status.warn('⚠️', `Failed to load ${logInfo}`)
                    void processError(server, pluginConfig, error)
                    resolve(null)
                }
            }
            this.failInitialization = () => {
                resolve(null)
            }
        })
    }

    async getOnEvent(): Promise<PluginConfigVMReponse['methods']['onEvent'] | null> {
        return (await this.resolveInternalVm)?.methods.onEvent || null
    }

    async getOnSnapshot(): Promise<PluginConfigVMReponse['methods']['onSnapshot'] | null> {
        return (await this.resolveInternalVm)?.methods.onSnapshot || null
    }

    async getProcessEvent(): Promise<PluginConfigVMReponse['methods']['processEvent'] | null> {
        return (await this.resolveInternalVm)?.methods.processEvent || null
    }

    async getProcessEventBatch(): Promise<PluginConfigVMReponse['methods']['processEventBatch'] | null> {
        return (await this.resolveInternalVm)?.methods.processEventBatch || null
    }

    async getTeardownPlugin(): Promise<PluginConfigVMReponse['methods']['teardownPlugin'] | null> {
        return (await this.resolveInternalVm)?.methods.teardownPlugin || null
    }

    async getTask(name: string, type: PluginTaskType): Promise<PluginTask | null> {
        return (await this.resolveInternalVm)?.tasks?.[type]?.[name] || null
    }

    async getTasks(type: PluginTaskType): Promise<Record<string, PluginTask>> {
        return (await this.resolveInternalVm)?.tasks?.[type] || {}
    }
}
