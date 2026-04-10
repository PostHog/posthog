import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'

import { ApiRequest } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import type { customerIOSyncLogicType } from './customerIOSyncLogicType'

export interface CustomerIOSyncStatus {
    configured: boolean
    site_id?: string | null
    region?: 'us' | 'eu'
    outbound_enabled: boolean
    webhook_configured: boolean
    webhook_url?: string
}

export interface CustomerIOSyncFormValues {
    site_id: string
    track_api_key: string
    webhook_signing_secret: string
    region: 'us' | 'eu'
}

const EMPTY_STATUS: CustomerIOSyncStatus = {
    configured: false,
    outbound_enabled: false,
    webhook_configured: false,
}

export const customerIOSyncLogic = kea<customerIOSyncLogicType>([
    path(['products', 'workflows', 'customerIOSyncLogic']),
    actions({
        openSyncModal: true,
        closeSyncModal: true,
        loadStatus: true,
        setStatus: (status: CustomerIOSyncStatus) => ({ status }),
        setStatusError: (error: string | null) => ({ error }),
        setStatusLoading: (loading: boolean) => ({ loading }),
    }),
    reducers({
        isSyncModalOpen: [
            false,
            {
                openSyncModal: () => true,
                closeSyncModal: () => false,
            },
        ],
        status: [
            EMPTY_STATUS as CustomerIOSyncStatus,
            {
                setStatus: (_, { status }) => status,
            },
        ],
        statusError: [
            null as string | null,
            {
                setStatusError: (_, { error }) => error,
                setStatus: () => null,
            },
        ],
        statusLoading: [
            false,
            {
                setStatusLoading: (_, { loading }) => loading,
            },
        ],
    }),
    forms(({ actions }) => ({
        syncForm: {
            defaults: {
                site_id: '',
                track_api_key: '',
                webhook_signing_secret: '',
                region: 'us',
            } as CustomerIOSyncFormValues,
            errors: ({ site_id, track_api_key, webhook_signing_secret }) => ({
                // All three fields are optional because the POST does a partial update —
                // but we require at least *one* non-empty value so the user can't submit
                // an empty form by accident.
                site_id:
                    !site_id && !track_api_key && !webhook_signing_secret
                        ? 'Provide at least one field to update'
                        : undefined,
            }),
            submit: async (values) => {
                // Strip empty strings so partial updates preserve the existing credential.
                const payload: Partial<CustomerIOSyncFormValues> = { region: values.region }
                if (values.site_id) {
                    payload.site_id = values.site_id
                }
                if (values.track_api_key) {
                    payload.track_api_key = values.track_api_key
                }
                if (values.webhook_signing_secret) {
                    payload.webhook_signing_secret = values.webhook_signing_secret
                }

                const response: CustomerIOSyncStatus = await new ApiRequest()
                    .messagingCategories()
                    .addPathComponent('customerio_sync')
                    .create({ data: payload })

                actions.setStatus(response)
                return response
            },
        },
    })),
    selectors({
        isSaving: [(s) => [s.isSyncFormSubmitting], (isSyncFormSubmitting) => isSyncFormSubmitting],
    }),
    listeners(({ actions }) => ({
        loadStatus: async () => {
            actions.setStatusLoading(true)
            try {
                const response: CustomerIOSyncStatus = await new ApiRequest()
                    .messagingCategories()
                    .addPathComponent('customerio_sync')
                    .get()
                actions.setStatus(response)
            } catch (error: any) {
                actions.setStatusError(error?.detail || 'Failed to load Customer.io sync status')
            } finally {
                actions.setStatusLoading(false)
            }
        },
        openSyncModal: () => {
            actions.loadStatus()
        },
        submitSyncFormSuccess: () => {
            lemonToast.success('Customer.io sync configuration saved')
        },
        submitSyncFormFailure: ({ error }: { error: any }) => {
            const detail = error?.detail || error?.message || 'Failed to save Customer.io sync configuration'
            lemonToast.error(detail)
        },
        closeSyncModal: () => {
            actions.resetSyncForm()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadStatus()
    }),
])
