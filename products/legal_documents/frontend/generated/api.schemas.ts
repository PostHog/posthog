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
    representative_email: string
    status: string
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
     * The customer legal entity entering the agreement (PandaDoc's Client.Company).
     * @maxLength 255
     */
    company_name: string
    /**
     * The customer address (PandaDoc's Client.StreetAddress).
     * @maxLength 512
     */
    company_address: string
    /** Email the signed PandaDoc envelope is sent to (PandaDoc's Client.Email). */
    representative_email: string
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
