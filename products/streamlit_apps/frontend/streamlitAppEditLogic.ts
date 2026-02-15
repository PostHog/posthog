import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import type { streamlitAppEditLogicType } from './streamlitAppEditLogicType'
import { streamlitAppsLogic } from './streamlitAppsLogic'
import { StreamlitAppType, StreamlitAppVersion } from './types'

export interface StreamlitAppEditLogicProps {
    shortId: string
}

export const streamlitAppEditLogic = kea<streamlitAppEditLogicType>([
    path(['products', 'streamlit_apps', 'frontend', 'streamlitAppEditLogic']),
    props({} as StreamlitAppEditLogicProps),
    key((props) => props.shortId),

    actions({
        setName: (name: string) => ({ name }),
        setDescription: (description: string) => ({ description }),
        setCpuCores: (cpuCores: number) => ({ cpuCores }),
        setMemoryGb: (memoryGb: number) => ({ memoryGb }),
        setZipFile: (file: File | null) => ({ file }),
        setActiveVersionNumber: (versionNumber: number) => ({ versionNumber }),
    }),

    loaders(({ props, values }) => ({
        streamlitApp: [
            null as StreamlitAppType | null,
            {
                loadStreamlitApp: async () => {
                    if (props.shortId === 'new') {
                        return null
                    }
                    return await api.streamlitApps.get(props.shortId)
                },
            },
        ],
        versions: [
            [] as StreamlitAppVersion[],
            {
                loadVersions: async () => {
                    if (props.shortId === 'new') {
                        return []
                    }
                    const response = await api.streamlitApps.versions(props.shortId)
                    return response.results
                },
            },
        ],
        savedApp: [
            null as StreamlitAppType | null,
            {
                saveApp: async () => {
                    const isNew = props.shortId === 'new'

                    let app: StreamlitAppType
                    if (isNew) {
                        app = await api.streamlitApps.create({
                            name: values.name,
                            description: values.description,
                            cpu_cores: values.cpuCores,
                            memory_gb: values.memoryGb,
                        })
                    } else {
                        app = await api.streamlitApps.update(props.shortId, {
                            name: values.name,
                            description: values.description,
                            cpu_cores: values.cpuCores,
                            memory_gb: values.memoryGb,
                        })
                    }

                    if (values.zipFile) {
                        await api.streamlitApps.uploadVersion(app.short_id, values.zipFile)
                        app = await api.streamlitApps.get(app.short_id)
                    }

                    lemonToast.success(isNew ? 'App created' : 'App saved')

                    streamlitAppsLogic.findMounted()?.actions.updateStreamlitApp(app)

                    if (isNew) {
                        router.actions.push(urls.streamlitApp(app.short_id))
                    }

                    return app
                },
                deleteApp: async () => {
                    await api.streamlitApps.delete(props.shortId)
                    lemonToast.success('App deleted')
                    streamlitAppsLogic.findMounted()?.actions.loadStreamlitApps()
                    router.actions.push(urls.streamlitApps())
                    return null
                },
            },
        ],
    })),

    reducers({
        name: [
            '',
            {
                setName: (_, { name }) => name,
                loadStreamlitAppSuccess: (_, { streamlitApp }) => streamlitApp?.name ?? '',
            },
        ],
        description: [
            '',
            {
                setDescription: (_, { description }) => description,
                loadStreamlitAppSuccess: (_, { streamlitApp }) => streamlitApp?.description ?? '',
            },
        ],
        cpuCores: [
            0.5,
            {
                setCpuCores: (_, { cpuCores }) => cpuCores,
                loadStreamlitAppSuccess: (_, { streamlitApp }) => streamlitApp?.cpu_cores ?? 0.5,
            },
        ],
        memoryGb: [
            1,
            {
                setMemoryGb: (_, { memoryGb }) => memoryGb,
                loadStreamlitAppSuccess: (_, { streamlitApp }) => streamlitApp?.memory_gb ?? 1,
            },
        ],
        zipFile: [
            null as File | null,
            {
                setZipFile: (_, { file }) => file,
            },
        ],
    }),

    listeners(({ props, actions }) => ({
        setActiveVersionNumber: async ({ versionNumber }) => {
            if (props.shortId === 'new') {
                return
            }
            const app = await api.streamlitApps.activateVersion(props.shortId, versionNumber)
            lemonToast.success(`Switched to v${versionNumber}`)
            streamlitAppsLogic.findMounted()?.actions.updateStreamlitApp(app)
            actions.loadStreamlitApp()
        },
    })),

    afterMount(({ props, actions }) => {
        if (props.shortId !== 'new') {
            actions.loadStreamlitApp()
            actions.loadVersions()
        }
    }),
])
