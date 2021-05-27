import equal from 'fast-deep-equal'

import {
    Hub,
    PluginCapabilities,
    PluginConfig,
    PluginConfigVMResponse,
    PluginLogEntrySource,
    PluginLogEntryType,
    PluginTask,
    PluginTaskType,
} from '../../types'
import { clearError, processError } from '../../utils/db/error'
import { disablePlugin, setPluginCapabilities } from '../../utils/db/sql'
import { status } from '../../utils/status'
import { createPluginConfigVM } from './vm'

export class LazyPluginVM {
    initialize?: (hub: Hub, pluginConfig: PluginConfig, indexJs: string, logInfo: string) => Promise<void>
    failInitialization?: () => void
    resolveInternalVm: Promise<PluginConfigVMResponse | null>

    constructor() {
        this.resolveInternalVm = new Promise((resolve) => {
            this.initialize = async (hub: Hub, pluginConfig: PluginConfig, indexJs: string, logInfo = '') => {
                try {
                    const vm = await createPluginConfigVM(hub, pluginConfig, indexJs)
                    await hub.db.createPluginLogEntry(
                        pluginConfig,
                        PluginLogEntrySource.System,
                        PluginLogEntryType.Info,
                        `Plugin loaded (instance ID ${hub.instanceId}).`,
                        hub.instanceId
                    )
                    status.info('🔌', `Loaded ${logInfo}`)
                    void clearError(hub, pluginConfig)
                    await this.inferPluginCapabilities(hub, pluginConfig, vm)
                    resolve(vm)
                } catch (error) {
                    await hub.db.createPluginLogEntry(
                        pluginConfig,
                        PluginLogEntrySource.System,
                        PluginLogEntryType.Error,
                        `Plugin failed to load and was disabled (instance ID ${hub.instanceId}).`,
                        hub.instanceId
                    )
                    status.warn('⚠️', `Failed to load ${logInfo}`)
                    void disablePlugin(hub, pluginConfig.id)
                    void processError(hub, pluginConfig, error)
                    resolve(null)
                }
            }
            this.failInitialization = () => {
                resolve(null)
            }
        })
    }

    async getExportEvents(): Promise<PluginConfigVMResponse['methods']['exportEvents'] | null> {
        return (await this.resolveInternalVm)?.methods.exportEvents || null
    }

    async getOnEvent(): Promise<PluginConfigVMResponse['methods']['onEvent'] | null> {
        return (await this.resolveInternalVm)?.methods.onEvent || null
    }

    async getOnSnapshot(): Promise<PluginConfigVMResponse['methods']['onSnapshot'] | null> {
        return (await this.resolveInternalVm)?.methods.onSnapshot || null
    }

    async getProcessEvent(): Promise<PluginConfigVMResponse['methods']['processEvent'] | null> {
        return (await this.resolveInternalVm)?.methods.processEvent || null
    }

    async getProcessEventBatch(): Promise<PluginConfigVMResponse['methods']['processEventBatch'] | null> {
        return (await this.resolveInternalVm)?.methods.processEventBatch || null
    }

    async getTeardownPlugin(): Promise<PluginConfigVMResponse['methods']['teardownPlugin'] | null> {
        return (await this.resolveInternalVm)?.methods.teardownPlugin || null
    }

    async getTask(name: string, type: PluginTaskType): Promise<PluginTask | null> {
        return (await this.resolveInternalVm)?.tasks?.[type]?.[name] || null
    }

    async getTasks(type: PluginTaskType): Promise<Record<string, PluginTask>> {
        return (await this.resolveInternalVm)?.tasks?.[type] || {}
    }

    private async inferPluginCapabilities(
        hub: Hub,
        pluginConfig: PluginConfig,
        vm: PluginConfigVMResponse
    ): Promise<void> {
        if (!pluginConfig.plugin) {
            throw new Error(`'PluginConfig missing plugin: ${pluginConfig}`)
        }

        const capabilities: Required<PluginCapabilities> = { scheduled_tasks: [], jobs: [], methods: [] }

        const tasks = vm?.tasks
        const methods = vm?.methods

        if (methods) {
            for (const [key, value] of Object.entries(methods)) {
                if (value) {
                    capabilities.methods.push(key)
                }
            }
        }

        if (tasks?.schedule) {
            for (const [key, value] of Object.entries(tasks.schedule)) {
                if (value) {
                    capabilities.scheduled_tasks.push(key)
                }
            }
        }

        if (tasks?.job) {
            for (const [key, value] of Object.entries(tasks.job)) {
                if (value) {
                    capabilities.jobs.push(key)
                }
            }
        }

        const prevCapabilities = pluginConfig.plugin.capabilities
        if (!equal(prevCapabilities, capabilities)) {
            await setPluginCapabilities(hub, pluginConfig, capabilities)
            pluginConfig.plugin.capabilities = capabilities
        }
    }
}
