import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { BillingType } from '~/types'

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
    representative_name: string
    representative_email: string
    status: LegalDocumentStatus
    signed_document_url: string
    created_by: LegalDocumentCreator | null
    created_at: string
}

export interface LegalDocumentFormValues {
    document_type: LegalDocumentType
    company_name: string
    company_address: string
    representative_name: string
    representative_title: string
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
        representative_name: '',
        representative_title: '',
        representative_email: '',
        dpa_mode: documentType === 'DPA' ? 'pretty' : '',
    }
}

export const legalDocumentsLogic = kea<legalDocumentsLogicType>([
    path(['products', 'legal_documents', 'legalDocumentsLogic']),
    connect(() => ({
        values: [organizationLogic, ['currentOrganization', 'currentOrganizationId'], billingLogic, ['billing']],
    })),
    actions({
        setDocumentType: (documentType: LegalDocumentType) => ({ documentType }),
        setDpaMode: (dpaMode: DPAMode) => ({ dpaMode }),
    }),
    loaders(({ values }) => ({
        legalDocuments: [
            [] as LegalDocument[],
            {
                loadLegalDocuments: async () => {
                    if (!values.currentOrganizationId) {
                        return []
                    }
                    const response = await api.get(`api/organizations/${values.currentOrganizationId}/legal_documents`)
                    return (response.results ?? []) as LegalDocument[]
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
                representative_name,
                representative_title,
                representative_email,
                dpa_mode,
            }: LegalDocumentFormValues) => ({
                company_name: !company_name ? 'Company name is required' : undefined,
                representative_name: !representative_name ? 'Representative name is required' : undefined,
                representative_title: !representative_title ? 'Representative title is required' : undefined,
                representative_email: !representative_email
                    ? 'Representative email is required'
                    : !representative_email.includes('@')
                      ? 'Enter a valid email'
                      : undefined,
                ...(document_type === 'DPA'
                    ? {
                          company_address: !company_address ? 'Company address is required' : undefined,
                          dpa_mode: !DPA_SUBMITTABLE_MODES.has(dpa_mode as DPAMode)
                              ? "Pick 'pretty' or 'lawyer' to submit"
                              : undefined,
                      }
                    : {}),
            }),
            submit: async (formValues: LegalDocumentFormValues) => {
                const payload: Partial<LegalDocumentFormValues> = { ...formValues }
                if (payload.document_type === 'BAA') {
                    delete payload.company_address
                    delete payload.dpa_mode
                }
                try {
                    const legalDocument = await api.create<LegalDocument>(
                        `api/organizations/${values.currentOrganizationId}/legal_documents`,
                        payload
                    )
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
