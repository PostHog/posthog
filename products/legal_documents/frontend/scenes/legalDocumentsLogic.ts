import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { BillingType } from '~/types'

import * as api from '../generated/api'
import type { legalDocumentsLogicType } from './legalDocumentsLogicType'

export type LegalDocumentType = 'BAA' | 'DPA'
export type DPAMode = 'pretty' | 'lawyer' | 'fairytale' | 'tswift'
export type LegalDocumentStatus = 'submitted_for_signature' | 'signed'

export interface LegalDocumentCreator {
    first_name: string
    email: string
}

export interface LegalDocument {
    id: string
    document_type: LegalDocumentType
    company_name: string
    representative_email: string
    status: LegalDocumentStatus
    created_by: LegalDocumentCreator | null
    created_at: string
}

export interface LegalDocumentFormValues {
    document_type: LegalDocumentType
    company_name: string
    company_address: string
    representative_email: string
    dpa_mode: DPAMode | ''
}

const BAA_ADDON_TYPES = new Set(['boost', 'scale', 'enterprise'])
export const DPA_SUBMITTABLE_MODES = new Set<DPAMode>(['pretty', 'lawyer'])
const ALLOWED_NEW_TYPES = new Set<LegalDocumentType>(['BAA', 'DPA'])

function defaultsFor(documentType: LegalDocumentType): LegalDocumentFormValues {
    return {
        document_type: documentType,
        company_name: '',
        company_address: '',
        representative_email: '',
        dpa_mode: documentType === 'DPA' ? 'pretty' : '',
    }
}

export const legalDocumentsLogic = kea<legalDocumentsLogicType>([
    path(['products', 'legal_documents', 'legalDocumentsLogic']),
    connect(() => ({
        values: [
            organizationLogic,
            ['currentOrganization', 'currentOrganizationId', 'isAdminOrOwner'],
            billingLogic,
            ['billing'],
        ],
        actions: [organizationLogic, ['loadCurrentOrganizationSuccess']],
    })),
    actions({
        setDocumentType: (documentType: LegalDocumentType) => ({ documentType }),
        setDpaMode: (dpaMode: DPAMode) => ({ dpaMode }),
        deleteLegalDocument: (id: string, documentType: LegalDocumentType) => ({ id, documentType }),
        // Internal — used by the listener to drive the per-row spinner.
        setDeletingId: (id: string | null) => ({ id }),
    }),
    reducers({
        deletingId: [
            null as string | null,
            {
                setDeletingId: (_, { id }) => id,
            },
        ],
    }),
    loaders(({ values }) => ({
        legalDocuments: [
            [] as LegalDocument[],
            {
                loadLegalDocuments: async () => {
                    if (!values.currentOrganizationId) {
                        return []
                    }
                    if (values.isAdminOrOwner === false && values.currentOrganization) {
                        return []
                    }
                    try {
                        const response = await api.legalDocumentsList(values.currentOrganizationId)
                        return (response.results ?? []) as LegalDocument[]
                    } catch (error) {
                        if (error instanceof ApiError && error.status === 403) {
                            return []
                        }
                        throw error
                    }
                },
            },
        ],
    })),
    forms(({ values, actions }) => ({
        legalDocument: {
            defaults: defaultsFor('DPA'),
            errors: ({
                document_type,
                company_name,
                company_address,
                representative_email,
                dpa_mode,
            }: LegalDocumentFormValues) => ({
                company_name: !company_name ? 'Company name is required' : undefined,
                company_address: !company_address ? 'Company address is required' : undefined,
                representative_email: !representative_email
                    ? 'Signer email is required'
                    : !representative_email.includes('@')
                      ? 'Enter a valid email'
                      : undefined,
                ...(document_type === 'DPA' && !DPA_SUBMITTABLE_MODES.has(dpa_mode as DPAMode)
                    ? { dpa_mode: "Pick 'pretty' or 'lawyer' to submit" }
                    : {}),
            }),
            submit: async (formValues: LegalDocumentFormValues) => {
                // dpa_mode is a preview-only toggle — the backend generates a
                // single DPA variant, so we never send it on the wire.
                const { dpa_mode: _dpaMode, ...payload } = formValues
                try {
                    const legalDocument = await api.legalDocumentsCreate(values.currentOrganizationId, payload)
                    actions.loadLegalDocuments()
                    actions.resetLegalDocument(defaultsFor(formValues.document_type))
                    lemonToast.success(
                        `${legalDocument.document_type} submitted. Watch your inbox for a PandaDoc envelope.`
                    )
                    router.actions.push(urls.legalDocuments())
                } catch (error: any) {
                    lemonToast.error(error?.detail || 'Could not submit the document. Please try again.')
                    throw error
                }
            },
        },
    })),
    listeners(({ values, actions }) => ({
        setDocumentType: ({ documentType }) => {
            actions.setLegalDocumentValue('document_type', documentType)
            if (documentType === 'DPA' && !values.legalDocument.dpa_mode) {
                actions.setLegalDocumentValue('dpa_mode', 'pretty')
            } else if (documentType === 'BAA') {
                actions.setLegalDocumentValue('dpa_mode', '')
            }
        },
        setDpaMode: ({ dpaMode }) => {
            actions.setLegalDocumentValue('dpa_mode', dpaMode)
        },
        deleteLegalDocument: async ({ id, documentType }) => {
            if (!values.currentOrganizationId) {
                return
            }
            actions.setDeletingId(id)
            try {
                await api.legalDocumentsDestroy(values.currentOrganizationId, id)
                actions.loadLegalDocuments()
                lemonToast.success(`${documentType} deleted. You can now generate a new ${documentType}.`)
            } catch (error: any) {
                // 503 from the backend means the PandaDoc envelope couldn't be
                // cancelled and the row was NOT deleted — surface the backend's
                // detail so the user knows to retry rather than assuming success.
                lemonToast.error(
                    error?.detail ||
                        `Could not delete the ${documentType}. Please try again, or contact PostHog support.`
                )
            } finally {
                actions.setDeletingId(null)
            }
        },
        loadCurrentOrganizationSuccess: () => {
            if (values.legalDocuments.length === 0 && values.isAdminOrOwner && !values.legalDocumentsLoading) {
                actions.loadLegalDocuments()
            }
        },
    })),
    selectors({
        hasQualifyingBaaAddon: [
            (s) => [s.billing],
            (billing: BillingType | null): boolean => {
                if (!billing?.products) {
                    return false
                }
                return billing.products.some((product) =>
                    product.addons?.some((addon) => BAA_ADDON_TYPES.has(addon.type) && !!addon.subscribed)
                )
            },
        ],
        isOnQualifyingAddonTrial: [
            (s) => [s.billing],
            (billing: BillingType | null): boolean => {
                if (!billing?.trial) {
                    return false
                }
                return billing.trial.status === 'active' && BAA_ADDON_TYPES.has(billing.trial.target)
            },
        ],
        // Enterprise 'standard' trials are sales-managed: the billing page hides
        // the cancel-trial button for them (see BillingProductAddonActions.tsx),
        // so users need to go through support to convert their trial.
        isOnEnterpriseStandardTrial: [
            (s) => [s.billing],
            (billing: BillingType | null): boolean => {
                if (!billing?.trial) {
                    return false
                }
                return (
                    billing.trial.status === 'active' &&
                    billing.trial.target === 'enterprise' &&
                    billing.trial.type !== 'autosubscribe'
                )
            },
        ],
        isDpaModeSubmittable: [
            (s) => [s.legalDocument],
            (form: LegalDocumentFormValues): boolean => DPA_SUBMITTABLE_MODES.has(form.dpa_mode as DPAMode),
        ],
        existingDocumentTypes: [
            (s) => [s.legalDocuments],
            (documents: LegalDocument[]): Set<LegalDocumentType> => new Set(documents.map((doc) => doc.document_type)),
        ],
        existingDocumentOfCurrentType: [
            (s) => [s.legalDocument, s.legalDocuments],
            (form: LegalDocumentFormValues, documents: LegalDocument[]): LegalDocument | null =>
                documents.find((doc) => doc.document_type === form.document_type) ?? null,
        ],
    }),
    urlToAction(({ actions }) => ({
        '/legal/new/:type': ({ type }) => {
            const upper = (type || '').toUpperCase() as LegalDocumentType
            const normalized: LegalDocumentType = ALLOWED_NEW_TYPES.has(upper) ? upper : 'DPA'
            actions.resetLegalDocument(defaultsFor(normalized))
        },
    })),
    afterMount(({ actions }) => {
        actions.loadLegalDocuments()
    }),
])
