import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'

import { ApiRequest, getCookie } from 'lib/api'
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

export const customerIOImportLogic = kea<customerIOImportLogicType>([
    path(['products', 'workflows', 'customerIOImportLogic']),
    actions({
        openImportModal: true,
        closeImportModal: true,
        resetImport: true,
        setImportProgress: (importProgress: ImportProgress) => ({ importProgress }),
        setImportError: (error: string | null) => ({ error }),
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

                    // Set the import progress directly (no polling)
                    actions.setImportProgress(response)
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
                const categoriesCreated = importProgress.categories_created || 0
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
                const errorMessage = importProgress.errors?.join(', ') || 'Import failed'
                lemonToast.error(errorMessage)
            }
        },
        uploadCSV: async () => {
            const CSRF_COOKIE_NAME = 'posthog_csrftoken'
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
                const response = await fetch(
                    '/api/environments/@current/messaging_categories/import_preferences_csv/',
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
                    console.error('CSV upload failed:', response.status, errorText)
                    throw new Error(errorText || `Upload failed with status ${response.status}`)
                }

                const data = await response.json()
                actions.setCSVProgress(data)

                if (data.status === 'completed') {
                    lemonToast.success(
                        `CSV import completed! Processed ${data.rows_processed} rows with ${data.users_with_optouts} users having opt-outs.`
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
            actions.resetImportForm()
            actions.resetImport()
        },
    })),
])
