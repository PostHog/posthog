import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

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
        values: [organizationLogic, ['currentOrganization', 'currentOrganizationId'], billingLogic, ['billing']],
    })),
    actions({
        setDocumentType: (documentType: LegalDocumentType) => ({ documentType }),
        setDpaMode: (dpaMode: DPAMode) => ({ dpaMode }),
        // Open the signed-PDF download in a new tab once we've confirmed the
        // file actually exists. Probing the redirect endpoint lets us turn a
        // would-be silent 404-in-new-tab into an inline retry affordance.
        requestSignedPdfDownload: (documentId: string) => ({ documentId }),
        markSignedPdfUnavailable: (documentId: string) => ({ documentId }),
        clearSignedPdfUnavailable: (documentId: string) => ({ documentId }),
        setSignedPdfDownloadPending: (documentId: string, pending: boolean) => ({ documentId, pending }),
    }),
    reducers({
        // Document ids whose latest download probe came back 404 — surfaced as
        // an inline "not yet available, try again shortly" hint in the table.
        unavailableSignedPdfIds: [
            new Set<string>(),
            {
                markSignedPdfUnavailable: (state: Set<string>, { documentId }: { documentId: string }) => {
                    if (state.has(documentId)) {
                        return state
                    }
                    const next = new Set(state)
                    next.add(documentId)
                    return next
                },
                clearSignedPdfUnavailable: (state: Set<string>, { documentId }: { documentId: string }) => {
                    if (!state.has(documentId)) {
                        return state
                    }
                    const next = new Set(state)
                    next.delete(documentId)
                    return next
                },
            },
        ],
        // Per-row loading state, so the Download button stays disabled with a
        // spinner while we probe — guards against double-clicks generating
        // duplicate presigned URLs.
        pendingSignedPdfIds: [
            new Set<string>(),
            {
                setSignedPdfDownloadPending: (
                    state: Set<string>,
                    { documentId, pending }: { documentId: string; pending: boolean }
                ) => {
                    const has = state.has(documentId)
                    if (pending === has) {
                        return state
                    }
                    const next = new Set(state)
                    if (pending) {
                        next.add(documentId)
                    } else {
                        next.delete(documentId)
                    }
                    return next
                },
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
                    const response = await api.legalDocumentsList(values.currentOrganizationId)
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
        requestSignedPdfDownload: async ({ documentId }) => {
            const organizationId = values.currentOrganizationId
            if (!organizationId) {
                return
            }
            if (values.pendingSignedPdfIds.has(documentId)) {
                return
            }
            actions.clearSignedPdfUnavailable(documentId)
            actions.setSignedPdfDownloadPending(documentId, true)
            const url = api.getLegalDocumentsDownloadRetrieveUrl(organizationId, documentId)
            try {
                // Probe with `redirect: 'manual'` so we don't actually download
                // the PDF (and burn S3 egress) just to test that the file
                // exists — a healthy response is a 302, which fetch surfaces
                // as an `opaqueredirect`. A 404 means the upload from
                // PandaDoc hasn't landed in object storage yet.
                const response = await fetch(url, { credentials: 'same-origin', redirect: 'manual' })
                if (response.type === 'opaqueredirect' || (response.status >= 200 && response.status < 400)) {
                    window.open(url, '_blank', 'noopener,noreferrer')
                    return
                }
                if (response.status === 404) {
                    actions.markSignedPdfUnavailable(documentId)
                    return
                }
                lemonToast.error(
                    `Couldn't open the signed copy (HTTP ${response.status}). Please try again shortly.`
                )
            } catch (_error) {
                lemonToast.error("Couldn't reach PostHog to fetch the signed copy. Please try again shortly.")
            } finally {
                actions.setSignedPdfDownloadPending(documentId, false)
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
