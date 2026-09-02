import type { SupportFormFields } from 'lib/components/Support/supportLogic'

import type { LegalDocument } from './legalDocumentsLogic'

export const FIELD_IDS = {
    company_name: 'legal-document-company-name',
    company_address: 'legal-document-company-address',
    representative_email: 'legal-document-representative-email',
} as const

export type LegalDocumentFieldId = (typeof FIELD_IDS)[keyof typeof FIELD_IDS]

/**
 * Why a document type can't be generated again. A signed document is a legal
 * record only support can replace, while an unsigned one the user can delete.
 */
export function alreadyExistsReason(existing: LegalDocument | undefined): string | undefined {
    if (!existing) {
        return undefined
    }
    return existing.status === 'signed'
        ? `Your organization already has a signed ${existing.document_type}. Contact support to replace it.`
        : `Your organization already has a ${existing.document_type} waiting for signature. Delete it to start a new one.`
}

/** Support form prefilled with the request to replace an already signed document. */
export function replaceDocumentSupportForm(existing: LegalDocument): Partial<SupportFormFields> {
    return {
        kind: 'support',
        isEmailFormOpen: true,
        message: `We need to replace the ${existing.document_type} signed for ${existing.company_name}.`,
    }
}
