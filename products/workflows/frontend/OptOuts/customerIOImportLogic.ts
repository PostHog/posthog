import { actions, beforeUnmount, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'

import { ApiRequest } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import type { customerIOImportLogicType } from './customerIOImportLogicType'
import { optOutCategoriesLogic } from './optOutCategoriesLogic'

export interface ImportFormValues {
    app_api_key: string
}

export interface CategoryProgress {
    name: string
    status: 'pending' | 'processing' | 'completed'
    preferences_count: number
}

export interface ImportProgress {
    status: string
    topics_found: number
    workflows_created?: number
    categories_created?: number
    customers_processed: number
    preferences_updated: number
    globally_unsubscribed_count?: number
    current_batch?: number
    customers_in_current_batch?: number
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
    current_batch: number
    details: string
    failed_imports?: Array<{
        email: string
        error: string
    }>
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
        setCSVFile: (file: File | null) => ({ file }),
        uploadCSV: true,
        setCSVProgress: (csvProgress: CSVImportProgress | null) => ({ csvProgress }),
        setShowCSVPhase: (show: boolean) => ({ show }),
        setIsUploadingCSV: (isUploading: boolean) => ({ isUploading }),
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
        showCSVPhase: [
            false,
            {
                setShowCSVPhase: (_, { show }) => show,
                resetImport: () => false,
                closeImportModal: () => false,
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
                const globallyUnsubscribed = importProgress.globally_unsubscribed_count || 0
                lemonToast.success(
                    `API import completed! Created ${categoriesCreated} categories and imported ${globallyUnsubscribed} globally unsubscribed users.`
                )
                // Show CSV phase after API import completes
                actions.setShowCSVPhase(true)
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
        uploadCSV: async () => {
            const file = customerIOImportLogic.values.csvFile
            if (!file) {
                lemonToast.error('Please select a CSV file')
                return
            }
            
            actions.setIsUploadingCSV(true)
            actions.setCSVProgress(null) // Clear any previous progress
            
            const formData = new FormData()
            formData.append('csv_file', file)
            
            try {
                // Get CSRF token from cookie (using PostHog's cookie name)
                const getCookie = (name: string): string | null => {
                    let cookieValue: string | null = null
                    if (document.cookie && document.cookie !== '') {
                        for (let cookie of document.cookie.split(';')) {
                            cookie = cookie.trim()
                            // Does this cookie string begin with the name we want?
                            if (cookie.substring(0, name.length + 1) === name + '=') {
                                cookieValue = decodeURIComponent(cookie.substring(name.length + 1))
                                break
                            }
                        }
                    }
                    return cookieValue
                }
                
                // Make a direct fetch request since ApiRequest might not handle multipart/form-data correctly
                const response = await fetch('/api/environments/@current/messaging_categories/import_preferences_csv/', {
                    method: 'POST',
                    body: formData,
                    credentials: 'include',
                    headers: {
                        // Don't set Content-Type header - let browser set it with boundary for multipart
                        'X-CSRFToken': getCookie('posthog_csrftoken') || '',
                    },
                })
                
                if (!response.ok) {
                    const errorText = await response.text()
                    console.error('CSV upload failed:', response.status, errorText)
                    throw new Error(errorText || `Upload failed with status ${response.status}`)
                }
                
                const data = await response.json()
                actions.setCSVProgress(data)
                
                if (data.status === 'completed') {
                    lemonToast.success(
                        `CSV import completed! Imported ${data.users_with_optouts} users with ${data.preferences_updated} opt-outs.`
                    )
                    // Refresh categories
                    if (window.location.pathname.includes('workflows')) {
                        optOutCategoriesLogic.actions.loadCategories()
                    }
                } else if (data.status === 'failed') {
                    lemonToast.error(data.details || 'CSV import failed')
                }
            } catch (error: any) {
                console.error('CSV upload error:', error)
                lemonToast.error(error.message || error.detail || 'Failed to upload CSV')
            } finally {
                actions.setIsUploadingCSV(false)
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
