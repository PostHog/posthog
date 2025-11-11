import { actions, beforeUnmount, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'

import { ApiRequest } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import type { customerIOImportLogicType } from './customerIOImportLogicType'
import { optOutCategoriesLogic } from './optOutCategoriesLogic'

export interface ImportFormValues {
    app_api_key: string
}

export interface ImportProgress {
    status: string
    topics_found: number
    workflows_created?: number
    categories_created?: number
    customers_processed: number
    preferences_updated: number
    current_category?: string
    current_category_index?: number
    total_categories?: number
    current_batch?: number
    customers_in_current_batch?: number
    details?: string
    errors: string[]
}

let pollInterval: NodeJS.Timeout | null = null

export const customerIOImportLogic = kea<customerIOImportLogicType>([
    path(['products', 'workflows', 'customerIOImportLogic']),
    actions({
        openImportModal: true,
        closeImportModal: true,
        resetImport: true,
        setImportProgress: (importProgress: ImportProgress) => ({ importProgress }),
        setImportError: (error: string | null) => ({ error }),
        startPolling: (importId: string) => ({ importId }),
        stopPolling: true,
        pollProgress: (importId: string) => ({ importId }),
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
                closeImportModal: () => null,
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
                closeImportModal: () => null,
            },
        ],
        currentImportId: [
            null as string | null,
            {
                startPolling: (_, { importId }) => importId,
                stopPolling: () => null,
                closeImportModal: () => null,
            },
        ],
    }),
    forms(({ actions }) => ({
        importForm: {
            defaults: {
                app_api_key: '',
            } as ImportFormValues,
            submit: async ({ app_api_key }) => {
                try {
                    const response = await new ApiRequest()
                        .messagingCategoriesImportFromCustomerIO()
                        .create({ data: { app_api_key } })

                    // The API now returns immediately with import_id
                    if (response.import_id) {
                        actions.startPolling(response.import_id)
                    } else {
                        // Legacy behavior for backward compatibility
                        actions.setImportProgress(response)
                    }

                    return response
                } catch (error: any) {
                    throw error
                }
            },
        },
    })),
    selectors({
        isImporting: [(s) => [s.isImportFormSubmitting], (isImportFormSubmitting) => isImportFormSubmitting],
        isImportComplete: [(s) => [s.importProgress], (importProgress) => importProgress?.status === 'completed'],
        isImportFailed: [(s) => [s.importProgress], (importProgress) => importProgress?.status === 'failed'],
    }),
    listeners(({ actions }) => ({
        setImportProgress: ({ importProgress }) => {
            if (importProgress.status === 'completed') {
                actions.stopPolling()
                const categoriesCreated = importProgress.categories_created || importProgress.workflows_created || 0
                lemonToast.success(
                    `Import completed! Created ${categoriesCreated} categories and imported ${importProgress.preferences_updated} opt-outs.`
                )
                // Refresh the categories list without reloading the page
                if (window.location.pathname.includes('workflows')) {
                    // Refresh the categories
                    optOutCategoriesLogic.actions.loadCategories()
                }
            } else if (importProgress.status === 'failed') {
                actions.stopPolling()
                const errorMessage = importProgress.errors?.join(', ') || 'Import failed'
                lemonToast.error(errorMessage)
            }
        },
        submitImportFormFailure: ({ error }) => {
            console.error('Import failed:', error)
        },
        closeImportModal: () => {
            actions.stopPolling()
            actions.resetImportForm()
            actions.resetImport()
        },
        startPolling: async ({ importId }) => {
            // Clear any existing interval
            if (pollInterval) {
                clearInterval(pollInterval)
            }

            // Start polling every 2 seconds
            pollInterval = setInterval(() => {
                actions.pollProgress(importId)
            }, 2000)

            // Do initial poll immediately
            actions.pollProgress(importId)
        },
        stopPolling: () => {
            if (pollInterval) {
                clearInterval(pollInterval)
                pollInterval = null
            }
        },
        pollProgress: async ({ importId }) => {
            try {
                const response = await new ApiRequest()
                    .messagingCategoriesImportProgress()
                    .withQueryString({ import_id: importId })
                    .get()

                actions.setImportProgress(response)
            } catch (error) {
                console.error('Failed to poll progress:', error)
                // Don't stop polling on error, might be temporary
            }
        },
    })),
    beforeUnmount(({ actions }) => {
        actions.stopPolling()
    }),
])
