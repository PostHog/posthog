/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface LegalDocumentCreatorApi {
    first_name: string
    email: string
}

/**
 * Output serializer — what the API returns for every row.
 */
export interface LegalDocumentDTOApi {
    id: string
    document_type: string
    company_name: string
    representative_name: string
    representative_email: string
    status: string
    signed_document_url: string
    created_by: LegalDocumentCreatorApi | null
    created_at: string
}

export interface PaginatedLegalDocumentDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: LegalDocumentDTOApi[]
}

/**
 * * `BAA` - BAA
 * `DPA` - DPA
 */
export type DocumentTypeEnumApi = (typeof DocumentTypeEnumApi)[keyof typeof DocumentTypeEnumApi]

export const DocumentTypeEnumApi = {
    Baa: 'BAA',
    Dpa: 'DPA',
} as const

/**
 * Input serializer for POST. Mirrors the submittable fields on the model plus
cross-field rules (BAA addon, DPA mode, uniqueness). The view supplies the
organization and submitting user.
 */
export interface CreateLegalDocumentApi {
    /** Either 'BAA' or 'DPA'.

* `BAA` - BAA
* `DPA` - DPA */
    document_type: DocumentTypeEnumApi
    /**
     * The customer legal entity entering the agreement.
     * @maxLength 255
     */
    company_name: string
    /**
     * Customer address. Required for DPAs; ignored for BAAs.
     * @maxLength 512
     */
    company_address?: string
    /**
     * Name of the signer at the customer.
     * @maxLength 255
     */
    representative_name: string
    /**
     * Title of the signer at the customer.
     * @maxLength 255
     */
    representative_title: string
    /** Email the signed PandaDoc envelope is sent to. */
    representative_email: string
    /**
     * DPA style: 'pretty' or 'lawyer' for submittable versions. 'fairytale' and 'tswift' are preview-only on posthog.com and are not accepted by the API.
     * @maxLength 16
     */
    dpa_mode?: string
}

export type LegalDocumentsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
