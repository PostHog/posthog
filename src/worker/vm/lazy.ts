import { clearError, processError } from '../../shared/error'
import { status } from '../../shared/status'
import { PluginConfig, PluginConfigVMReponse, PluginsServer, PluginTask } from '../../types'
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
                    status.info('🔌', `Loaded ${logInfo}`)
                    void clearError(server, pluginConfig)
                    resolve(vm)
                } catch (error) {
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

    async getProcessEvent(): Promise<PluginConfigVMReponse['methods']['processEvent'] | null> {
        return (await this.resolveInternalVm)?.methods.processEvent || null
    }

    async getProcessEventBatch(): Promise<PluginConfigVMReponse['methods']['processEventBatch'] | null> {
        return (await this.resolveInternalVm)?.methods.processEventBatch || null
    }

    async getTask(name: string): Promise<PluginTask | null> {
        return (await this.resolveInternalVm)?.tasks[name] || null
    }

    async getTasks(): Promise<Record<string, PluginTask>> {
        return (await this.resolveInternalVm)?.tasks || {}
    }
}
