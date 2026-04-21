/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `BAA` - Business Associate Agreement
 * `DPA` - Data Processing Agreement
 */
export type DocumentTypeEnumApi = (typeof DocumentTypeEnumApi)[keyof typeof DocumentTypeEnumApi]

export const DocumentTypeEnumApi = {
    Baa: 'BAA',
    Dpa: 'DPA',
} as const

/**
 * * `pretty` - A perfectly legal doc, but with some pizazz
 * `lawyer` - Drab and dull — preferred by lawyers
 * `fairytale` - A fairy tale story
 * `tswift` - Taylor Swift's version
 */
export type DpaModeEnumApi = (typeof DpaModeEnumApi)[keyof typeof DpaModeEnumApi]

export const DpaModeEnumApi = {
    Pretty: 'pretty',
    Lawyer: 'lawyer',
    Fairytale: 'fairytale',
    Tswift: 'tswift',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * * `submitted_for_signature` - Submitted for signature
 * `signed` - Signed
 */
export type LegalDocumentStatusEnumApi = (typeof LegalDocumentStatusEnumApi)[keyof typeof LegalDocumentStatusEnumApi]

export const LegalDocumentStatusEnumApi = {
    SubmittedForSignature: 'submitted_for_signature',
    Signed: 'signed',
} as const

export interface LegalDocumentApi {
    readonly id: string
    /** Either 'BAA' or 'DPA'.

* `BAA` - Business Associate Agreement
* `DPA` - Data Processing Agreement */
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
    /**
     * Email the signed PandaDoc envelope is sent to.
     * @maxLength 254
     */
    representative_email: string
    /** DPA style: 'pretty' or 'lawyer' for submittable versions. 'fairytale' and 'tswift' are preview-only on posthog.com and are not accepted by the API.

* `pretty` - A perfectly legal doc, but with some pizazz
* `lawyer` - Drab and dull — preferred by lawyers
* `fairytale` - A fairy tale story
* `tswift` - Taylor Swift's version */
    dpa_mode?: DpaModeEnumApi | BlankEnumApi
    /** Lifecycle: 'submitted_for_signature' until the PandaDoc signed-URL webhook flips it to 'signed'.

* `submitted_for_signature` - Submitted for signature
* `signed` - Signed */
    readonly status: LegalDocumentStatusEnumApi
    /** Download URL for the fully-signed PDF. Populated by PandaDoc via the public webhook. */
    readonly signed_document_url: string
    /** @nullable */
    readonly created_by: number | null
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedLegalDocumentListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: LegalDocumentApi[]
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
