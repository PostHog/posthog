import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { ApiRequest, getCookie } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import type { customerIOImportLogicType } from './customerIOImportLogicType'
import { optOutCategoriesLogic } from './optOutCategoriesLogic'

export interface ImportFormValues {
    app_api_key: string
}

export interface ImportProgress {
    status: string
    topics_found: number
    categories_created?: number
    globally_unsubscribed_count?: number
    details?: string
    errors: string[]
}

export interface CSVImportProgress {
    status: string
    total_rows: number
    rows_processed: number
    users_with_optouts: number
    users_skipped: number
    parse_errors: number
    preferences_updated: number
    total_unique_users?: number
    current_batch: number
    details: string
    failed_imports?: Array<{
        email: string
        error: string
    }>
}

export interface AppImportResult {
    status: 'completed' | 'failed'
    imported_at: string
    categories_created?: number
    globally_unsubscribed_count?: number
    error?: string
}

export interface CSVImportResult {
    status: 'completed' | 'failed'
    imported_at: string
    total_rows?: number
    users_with_optouts?: number
    users_skipped?: number
    parse_errors?: number
    error?: string
}

export interface OptOutSyncConfigResponse {
    app_integration_id: number | null
    app_import_result: AppImportResult | null
    csv_import_result: CSVImportResult | null
}

export const customerIOImportLogic = kea<customerIOImportLogicType>([
    path(['products', 'workflows', 'customerIOImportLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamIdStrict']],
    })),
    actions({
        openImportModal: true,
        closeImportModal: true,
        resetImport: true,
        setImportProgress: (importProgress: ImportProgress) => ({ importProgress }),
        setImportError: (error: string | null) => ({ error }),
        rerunImport: true,
        removeAppConfig: true,
        setCSVFile: (file: File | null) => ({ file }),
        uploadCSV: true,
        setCSVProgress: (csvProgress: CSVImportProgress | null) => ({ csvProgress }),
        setIsUploadingCSV: (isUploading: boolean) => ({ isUploading }),
    }),
    loaders({
        syncConfig: [
            null as OptOutSyncConfigResponse | null,
            {
                loadSyncConfig: async () => {
                    return await new ApiRequest().messagingCategoriesOptOutSyncConfig().get()
                },
            },
        ],
    }),
    reducers({
        isImportModalOpen: [
            false,
            {
                openImportModal: () => true,
                closeImportModal: () => false,
            },
        ],
        importProgress: [
            null as ImportProgress | null,
            {
                setImportProgress: (_, { importProgress }) => importProgress,
                resetImport: () => null,
            },
        ],
        importError: [
            null as string | null,
            {
                setImportError: (_, { error }) => error,
                submitImportFormFailure: (_, { error }) => {
                    if (error && typeof error === 'object' && 'detail' in error) {
                        return error.detail as string
                    }
                    return 'Import failed. Please check your API key and try again.'
                },
                submitImportFormSuccess: () => null,
                resetImport: () => null,
            },
        ],
        csvFile: [
            null as File | null,
            {
                setCSVFile: (_, { file }) => file,
                resetImport: () => null,
                closeImportModal: () => null,
            },
        ],
        csvProgress: [
            null as CSVImportProgress | null,
            {
                setCSVProgress: (_, { csvProgress }) => csvProgress,
                resetImport: () => null,
                closeImportModal: () => null,
            },
        ],
        isUploadingCSV: [
            false,
            {
                setIsUploadingCSV: (_, { isUploading }) => isUploading,
                resetImport: () => false,
                closeImportModal: () => false,
            },
        ],
        isRemovingAppConfig: [
            false,
            {
                removeAppConfig: () => true,
                loadSyncConfigSuccess: () => false,
                loadSyncConfigFailure: () => false,
            },
        ],
    }),
    forms(({ actions }) => ({
        importForm: {
            defaults: {
                app_api_key: '',
            } as ImportFormValues,
            submit: async ({ app_api_key }) => {
                const response = await new ApiRequest()
                    .messagingCategoriesImportFromCustomerIO()
                    .create({ data: { app_api_key } })

                actions.setImportProgress(response)
                // Reload config to pick up the newly created Integration
                actions.loadSyncConfig()
                return response
            },
        },
    })),
    selectors({
        isImporting: [
            (s) => [s.isImportFormSubmitting, s.importProgress],
            (isImportFormSubmitting, importProgress) =>
                isImportFormSubmitting || importProgress?.status === 'importing',
        ],
        isImportComplete: [(s) => [s.importProgress], (importProgress) => importProgress?.status === 'completed'],
        isImportFailed: [(s) => [s.importProgress], (importProgress) => importProgress?.status === 'failed'],
        stepCompletion: [
            (s) => [s.syncConfig, s.importProgress, s.csvProgress],
            (
                syncConfig,
                importProgress,
                csvProgress
            ): { step1: 'completed' | 'failed' | false; step2: 'completed' | 'failed' | false } => {
                const resolveStatus = (
                    localStatus: string | undefined,
                    persistedStatus: string | undefined
                ): 'completed' | 'failed' | false => {
                    const status = localStatus || persistedStatus
                    if (status === 'completed' || status === 'failed') {
                        return status
                    }
                    return false
                }

                return {
                    step1: resolveStatus(importProgress?.status, syncConfig?.app_import_result?.status),
                    step2: resolveStatus(csvProgress?.status, syncConfig?.csv_import_result?.status),
                }
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        openImportModal: () => {
            actions.loadSyncConfig()
        },
        removeAppConfig: async () => {
            try {
                await new ApiRequest().messagingCategoriesRemoveCustomerIOAppConfig().delete()
                actions.resetImport()
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to remove integration')
            } finally {
                actions.loadSyncConfig()
            }
        },
        rerunImport: async () => {
            actions.setImportProgress({ status: 'importing', topics_found: 0, errors: [] })
            try {
                const response = await new ApiRequest().messagingCategoriesImportFromCustomerIO().create({ data: {} })
                actions.setImportProgress(response)
                actions.loadSyncConfig()
            } catch (error: any) {
                actions.setImportProgress({
                    status: 'failed',
                    topics_found: 0,
                    errors: [error.detail || 'Import failed'],
                })
            }
        },
        setImportProgress: ({ importProgress }) => {
            if (importProgress.status === 'completed') {
                lemonToast.success('Customer.io API import completed!')
                optOutCategoriesLogic.findMounted()?.actions.loadCategories()
            } else if (importProgress.status === 'failed') {
                const errorMessage = importProgress.errors?.join(', ') || 'Import failed'
                lemonToast.error(errorMessage)
            }
        },
        uploadCSV: async () => {
            const CSRF_COOKIE_NAME = 'posthog_csrftoken'
            const file = values.csvFile
            if (!file) {
                lemonToast.error('Please select a CSV file')
                return
            }

            actions.setIsUploadingCSV(true)
            actions.setCSVProgress(null) // Clear any previous progress

            const formData = new FormData()
            formData.append('csv_file', file)

            try {
                const response = await fetch(
                    `/api/environments/${values.currentTeamIdStrict}/messaging_categories/import_preferences_csv/`,
                    {
                        method: 'POST',
                        body: formData,
                        credentials: 'include',
                        headers: {
                            'X-CSRFToken': getCookie(CSRF_COOKIE_NAME) || '',
                        },
                    }
                )

                if (!response.ok) {
                    const errorText = await response.text()
                    throw new Error(errorText || `Upload failed with status ${response.status}`)
                }

                const data = await response.json()
                actions.setCSVProgress(data)

                if (data.status === 'completed') {
                    lemonToast.success('CSV import completed.')
                    actions.loadSyncConfig()
                    optOutCategoriesLogic.findMounted()?.actions.loadCategories()
                } else if (data.status === 'failed') {
                    lemonToast.error(data.details || 'CSV import failed')
                }
            } catch (error: any) {
                lemonToast.error(error.message || error.detail || 'Failed to upload CSV')
            } finally {
                actions.setIsUploadingCSV(false)
            }
        },
        submitImportFormFailure: () => {},
        closeImportModal: () => {
            actions.resetImportForm()
            actions.resetImport()
        },
    })),
])
