import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { projectLogic } from 'scenes/projectLogic'
import { cloudEnvironmentsLogic, listAllPages } from 'scenes/settings/environment/cloudEnvironmentsLogic'

import { sandboxCustomImagesList } from 'products/tasks/frontend/generated/api'
import {
    type TasksTaskDefaultsApi,
    type SandboxCustomImageDTOApi,
    type SandboxEnvironmentDTOApi,
    SandboxCustomImagesListOriginProduct,
} from 'products/tasks/frontend/generated/api.schemas'

import { taskDefaultsLogic } from '../../logics/taskDefaultsLogic'
import { cloudTargetKey } from '../../utils/cloudTargets'
import { taskTrackerSceneLogic } from './taskTrackerSceneLogic'

export interface ComposerSandboxEnvironmentsLogicProps {
    panelId?: string
}

export interface composerSandboxEnvironmentsLogicValues {
    currentProjectId: number | null
    environments: SandboxEnvironmentDTOApi[] | null
    environmentsFailed: boolean
    taskDefaults: TasksTaskDefaultsApi | null
    myConfigLoading: boolean
    configFailed: boolean
    awaitingCreatedEnvironment: boolean
    images: SandboxCustomImageDTOApi[] | null
    imagesLoading: boolean
    imagesFailed: boolean
}

export interface composerSandboxEnvironmentsLogicActions {
    closeDraft: () => { value: true }
    environmentCreated: (environment: SandboxEnvironmentDTOApi) => { environment: SandboxEnvironmentDTOApi }
    loadEnvironments: () => any
    loadMyConfig: () => any
    loadEnvironmentsSuccess: (
        environments: SandboxEnvironmentDTOApi[] | null,
        payload?: any
    ) => { environments: SandboxEnvironmentDTOApi[] | null; payload?: any }
    startNewEnvironment: () => { value: true }
    pickCloudTarget: (cloudTarget: string | null) => { cloudTarget: string | null }
    setCloudTargets: (
        environments: SandboxEnvironmentDTOApi[] | null,
        images: SandboxCustomImageDTOApi[] | null
    ) => { environments: SandboxEnvironmentDTOApi[] | null; images: SandboxCustomImageDTOApi[] | null }
    createEnvironment: () => { value: true }
    syncCloudTargets: () => { value: true }
    retryCloudTargets: () => { value: true }
    loadImages: () => any
    loadImagesSuccess: (
        images: SandboxCustomImageDTOApi[] | null,
        payload?: any
    ) => { images: SandboxCustomImageDTOApi[] | null; payload?: any }
    loadImagesFailure: (error: string, errorObject?: any) => { error: string; errorObject?: any }
}

export type composerSandboxEnvironmentsLogicType = MakeLogicType<
    composerSandboxEnvironmentsLogicValues,
    composerSandboxEnvironmentsLogicActions,
    ComposerSandboxEnvironmentsLogicProps
>

export const composerSandboxEnvironmentsLogic = kea<composerSandboxEnvironmentsLogicType>([
    path(['products', 'posthog_ai', 'frontend', 'scenes', 'TaskTracker', 'composerSandboxEnvironmentsLogic']),
    props({} as ComposerSandboxEnvironmentsLogicProps),
    key((props) => props.panelId ?? 'scene'),
    connect((props: ComposerSandboxEnvironmentsLogicProps) => ({
        values: [
            projectLogic,
            ['currentProjectId'],
            cloudEnvironmentsLogic,
            ['environments', 'environmentsFailed'],
            taskDefaultsLogic,
            ['taskDefaults', 'myConfigLoading'],
        ],
        actions: [
            taskDefaultsLogic,
            ['loadMyConfig'],
            cloudEnvironmentsLogic,
            ['loadEnvironments', 'loadEnvironmentsSuccess', 'environmentCreated', 'closeDraft', 'startNewEnvironment'],
            taskTrackerSceneLogic({ panelId: props.panelId }),
            ['pickCloudTarget', 'setCloudTargets'],
        ],
    })),
    actions({
        createEnvironment: true,
        syncCloudTargets: true,
        retryCloudTargets: true,
    }),
    loaders(({ values }) => ({
        images: [
            null as SandboxCustomImageDTOApi[] | null,
            {
                loadImages: async (): Promise<SandboxCustomImageDTOApi[] | null> => {
                    if (values.currentProjectId == null) {
                        return null
                    }
                    const projectId = String(values.currentProjectId)
                    try {
                        const images = await listAllPages((params) =>
                            sandboxCustomImagesList(projectId, {
                                ...params,
                                origin_product: SandboxCustomImagesListOriginProduct.PosthogAi,
                            })
                        )
                        return images.filter((image) => image.status === 'ready')
                    } catch (error: any) {
                        if (error?.status === 403) {
                            return []
                        }
                        throw error
                    }
                },
            },
        ],
    })),
    reducers({
        awaitingCreatedEnvironment: [
            false,
            {
                createEnvironment: () => true,
                closeDraft: () => false,
            },
        ],
        imagesFailed: [
            false,
            {
                loadImages: () => false,
                loadImagesSuccess: () => false,
                loadImagesFailure: () => true,
            },
        ],
    }),
    selectors({
        configFailed: [
            (s) => [s.taskDefaults, s.myConfigLoading],
            (taskDefaults: TasksTaskDefaultsApi | null, myConfigLoading: boolean): boolean =>
                !taskDefaults && !myConfigLoading,
        ],
    }),
    listeners(({ actions, values }) => ({
        syncCloudTargets: () => {
            actions.setCloudTargets(values.environments, values.images)
        },
        loadEnvironmentsSuccess: () => actions.syncCloudTargets(),
        loadImagesSuccess: () => actions.syncCloudTargets(),
        retryCloudTargets: () => {
            if (values.environmentsFailed) {
                actions.loadEnvironments()
            }
            if (values.imagesFailed) {
                actions.loadImages()
            }
            if (values.configFailed) {
                actions.loadMyConfig()
            }
        },
        createEnvironment: () => {
            posthog.capture('task composer environment create started')
            actions.startNewEnvironment()
        },
        environmentCreated: ({ environment }) => {
            actions.syncCloudTargets()
            if (values.awaitingCreatedEnvironment) {
                posthog.capture('task composer environment created')
                actions.pickCloudTarget(cloudTargetKey('environment', environment.id))
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.syncCloudTargets()
        actions.loadImages()
    }),
])
