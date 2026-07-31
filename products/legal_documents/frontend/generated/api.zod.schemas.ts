/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const LegalDocumentCreatorApi = zod.object({
    first_name: zod.string(),
    email: zod.string(),
})

export type LegalDocumentCreatorApi = zod.input<typeof LegalDocumentCreatorApi>
export type LegalDocumentCreatorApiOutput = zod.output<typeof LegalDocumentCreatorApi>

export const LegalDocumentDTOApi = zod
    .object({
        id: zod.uuid(),
        document_type: zod.string(),
        company_name: zod.string(),
        representative_email: zod.string(),
        status: zod.string(),
        created_by: zod.union([LegalDocumentCreatorApi, zod.null()]),
        created_at: zod.iso.datetime({ offset: true }),
    })
    .describe('Output serializer — what the API returns for every row.')

export type LegalDocumentDTOApi = zod.input<typeof LegalDocumentDTOApi>
export type LegalDocumentDTOApiOutput = zod.output<typeof LegalDocumentDTOApi>

export const PaginatedLegalDocumentDTOListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(LegalDocumentDTOApi),
})

export type PaginatedLegalDocumentDTOListApi = zod.input<typeof PaginatedLegalDocumentDTOListApi>
export type PaginatedLegalDocumentDTOListApiOutput = zod.output<typeof PaginatedLegalDocumentDTOListApi>

export const CreateLegalDocumentDocumentTypeEnumApi = zod
    .enum(['BAA', 'DPA'])
    .describe('\* `BAA` - BAA\n\* `DPA` - DPA')

export type CreateLegalDocumentDocumentTypeEnumApi = zod.input<typeof CreateLegalDocumentDocumentTypeEnumApi>
export type CreateLegalDocumentDocumentTypeEnumApiOutput = zod.output<typeof CreateLegalDocumentDocumentTypeEnumApi>

export const createLegalDocumentApiCompanyNameMax = 255

export const createLegalDocumentApiCompanyAddressMax = 512

export const CreateLegalDocumentApi = zod
    .object({
        document_type: CreateLegalDocumentDocumentTypeEnumApi.describe(
            "Either 'BAA' or 'DPA'.\n\n\* `BAA` - BAA\n\* `DPA` - DPA"
        ),
        company_name: zod
            .string()
            .max(createLegalDocumentApiCompanyNameMax)
            .describe("The customer legal entity entering the agreement (PandaDoc's Client.Company)."),
        company_address: zod
            .string()
            .max(createLegalDocumentApiCompanyAddressMax)
            .describe("The customer address (PandaDoc's Client.StreetAddress)."),
        representative_email: zod
            .email()
            .describe("Email the signed PandaDoc envelope is sent to (PandaDoc's Client.Email)."),
    })
    .describe(
        'Input serializer for POST. Mirrors the submittable fields on the model plus\ncross-field rules (BAA addon, DPA mode, uniqueness). The view supplies the\norganization and submitting user.'
    )

export type CreateLegalDocumentApi = zod.input<typeof CreateLegalDocumentApi>
export type CreateLegalDocumentApiOutput = zod.output<typeof CreateLegalDocumentApi>
