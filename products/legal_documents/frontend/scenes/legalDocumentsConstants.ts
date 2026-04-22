export const FIELD_IDS = {
    company_name: 'legal-document-company-name',
    company_address: 'legal-document-company-address',
    representative_name: 'legal-document-representative-name',
    representative_title: 'legal-document-representative-title',
    representative_email: 'legal-document-representative-email',
} as const

export type LegalDocumentFieldId = (typeof FIELD_IDS)[keyof typeof FIELD_IDS]
