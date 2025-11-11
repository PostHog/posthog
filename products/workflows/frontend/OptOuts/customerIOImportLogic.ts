import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import type { customerIOImportLogicType } from './customerIOImportLogicType'

export interface ImportFormValues {
    app_api_key: string
}

export interface ImportProgress {
    status: string
    topics_found: number
    workflows_created: number
    customers_processed: number
    preferences_updated: number
    errors: string[]
}

export const customerIOImportLogic = kea<customerIOImportLogicType>([
    path(['products', 'workflows', 'customerIOImportLogic']),
    actions({
        openImportModal: true,
        closeImportModal: true,
        resetImport: true,
        setImportProgress: (importProgress: ImportProgress) => ({ importProgress }),
        setImportError: (error: string | null) => ({ error }),
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
    }),
    forms(({ actions }) => ({
        importForm: {
            defaults: {
                app_api_key: '',
            } as ImportFormValues,
            submit: async ({ app_api_key }) => {
                try {
                    const response = await api.create(
                        'api/projects/@current/message_categories/import_from_customerio',
                        {
                            app_api_key,
                        }
                    )
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
                lemonToast.success(
                    `Import completed! Created ${importProgress.workflows_created} workflows and updated ${importProgress.preferences_updated} preferences.`
                )
                // Reload the message categories after successful import
                if (window.location.pathname.includes('workflows')) {
                    // Trigger a refresh of the message categories
                    window.location.reload()
                }
            } else if (importProgress.status === 'failed') {
                const errorMessage = importProgress.errors?.join(', ') || 'Import failed'
                lemonToast.error(errorMessage)
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
