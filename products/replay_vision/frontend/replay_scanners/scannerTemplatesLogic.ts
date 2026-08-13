import { MakeLogicType, actions, afterMount, kea, listeners, path, reducers } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import {
    visionScannerTemplatesDestroy,
    visionScannerTemplatesList,
    visionScannersSaveAsTemplateCreate,
} from '../generated/api'
import type { ReplayScannerTemplateApi } from '../generated/api.schemas'

export interface scannerTemplatesLogicValues {
    customTemplates: ReplayScannerTemplateApi[]
    customTemplatesLoading: boolean
    deletingTemplateIds: string[]
    savingScannerIds: string[]
}

export interface scannerTemplatesLogicActions {
    deleteTemplate: (templateId: string) => { templateId: string }
    deleteTemplateFailure: (templateId: string) => { templateId: string }
    deleteTemplateSuccess: (templateId: string) => { templateId: string }
    loadTemplates: () => { value: true }
    loadTemplatesFailure: () => { value: true }
    loadTemplatesSuccess: (templates: ReplayScannerTemplateApi[]) => { templates: ReplayScannerTemplateApi[] }
    saveTemplate: (scannerId: string) => { scannerId: string }
    saveTemplateFailure: (scannerId: string) => { scannerId: string }
    saveTemplateSuccess: (
        scannerId: string,
        template: ReplayScannerTemplateApi
    ) => { scannerId: string; template: ReplayScannerTemplateApi }
}

export type scannerTemplatesLogicType = MakeLogicType<scannerTemplatesLogicValues, scannerTemplatesLogicActions>

function byName(left: ReplayScannerTemplateApi, right: ReplayScannerTemplateApi): number {
    return left.name.localeCompare(right.name)
}

export const scannerTemplatesLogic = kea<scannerTemplatesLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'scannerTemplatesLogic']),

    actions({
        loadTemplates: true,
        loadTemplatesSuccess: (templates: ReplayScannerTemplateApi[]) => ({ templates }),
        loadTemplatesFailure: true,
        saveTemplate: (scannerId: string) => ({ scannerId }),
        saveTemplateSuccess: (scannerId: string, template: ReplayScannerTemplateApi) => ({ scannerId, template }),
        saveTemplateFailure: (scannerId: string) => ({ scannerId }),
        deleteTemplate: (templateId: string) => ({ templateId }),
        deleteTemplateSuccess: (templateId: string) => ({ templateId }),
        deleteTemplateFailure: (templateId: string) => ({ templateId }),
    }),

    reducers({
        customTemplates: [
            [] as ReplayScannerTemplateApi[],
            {
                loadTemplatesSuccess: (_, { templates }) => [...templates].sort(byName),
                saveTemplateSuccess: (state, { template }) =>
                    [...state.filter((savedTemplate) => savedTemplate.id !== template.id), template].sort(byName),
                deleteTemplateSuccess: (state, { templateId }) =>
                    state.filter((template) => template.id !== templateId),
            },
        ],
        customTemplatesLoading: [
            true,
            {
                loadTemplates: () => true,
                loadTemplatesSuccess: () => false,
                loadTemplatesFailure: () => false,
            },
        ],
        savingScannerIds: [
            [] as string[],
            {
                saveTemplate: (state, { scannerId }) => [...new Set([...state, scannerId])],
                saveTemplateSuccess: (state, { scannerId }) => state.filter((id) => id !== scannerId),
                saveTemplateFailure: (state, { scannerId }) => state.filter((id) => id !== scannerId),
            },
        ],
        deletingTemplateIds: [
            [] as string[],
            {
                deleteTemplate: (state, { templateId }) => [...new Set([...state, templateId])],
                deleteTemplateSuccess: (state, { templateId }) => state.filter((id) => id !== templateId),
                deleteTemplateFailure: (state, { templateId }) => state.filter((id) => id !== templateId),
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        loadTemplates: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                actions.loadTemplatesFailure()
                return
            }
            try {
                const limit = 100
                const templates: ReplayScannerTemplateApi[] = []
                let offset = 0
                // Page through so teams with more than one page of templates don't silently lose the rest.
                for (;;) {
                    const response = await visionScannerTemplatesList(String(teamId), { limit, offset })
                    templates.push(...response.results)
                    if (!response.next) {
                        break
                    }
                    offset += limit
                }
                actions.loadTemplatesSuccess(templates)
            } catch (error: any) {
                lemonToast.error(`Failed to load scanner templates${error.detail ? `: ${error.detail}` : ''}`)
                actions.loadTemplatesFailure()
            }
        },
        saveTemplate: async ({ scannerId }) => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                actions.saveTemplateFailure(scannerId)
                return
            }
            const isUpdate = values.customTemplates.some((template) => template.source_scanner === scannerId)
            try {
                const template = await visionScannersSaveAsTemplateCreate(String(teamId), scannerId)
                actions.saveTemplateSuccess(scannerId, template)
                lemonToast.success(isUpdate ? 'Scanner template updated' : 'Scanner template saved')
            } catch (error: any) {
                lemonToast.error(`Failed to save scanner template${error.detail ? `: ${error.detail}` : ''}`)
                actions.saveTemplateFailure(scannerId)
            }
        },
        deleteTemplate: async ({ templateId }) => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                actions.deleteTemplateFailure(templateId)
                return
            }
            try {
                await visionScannerTemplatesDestroy(String(teamId), templateId)
                actions.deleteTemplateSuccess(templateId)
                lemonToast.success('Scanner template deleted')
            } catch (error: any) {
                lemonToast.error(`Failed to delete scanner template${error.detail ? `: ${error.detail}` : ''}`)
                actions.deleteTemplateFailure(templateId)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadTemplates()
    }),
])
