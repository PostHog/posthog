/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const legalDocumentsCreateBodyCompanyNameMax = 255

export const legalDocumentsCreateBodyCompanyAddressMax = 512

export const LegalDocumentsCreateBody = /* @__PURE__ */ zod
    .object({
        document_type: zod
            .enum(['BAA', 'DPA'])
            .describe('* `BAA` - BAA\n* `DPA` - DPA')
            .describe("Either 'BAA' or 'DPA'.\n\n* `BAA` - BAA\n* `DPA` - DPA"),
        company_name: zod
            .string()
            .max(legalDocumentsCreateBodyCompanyNameMax)
            .describe("The customer legal entity entering the agreement (PandaDoc's Client.Company)."),
        company_address: zod
            .string()
            .max(legalDocumentsCreateBodyCompanyAddressMax)
            .describe("The customer address (PandaDoc's Client.StreetAddress)."),
        representative_email: zod
            .email()
            .describe("Email the signed PandaDoc envelope is sent to (PandaDoc's Client.Email)."),
    })
    .describe(
        'Input serializer for POST. Mirrors the submittable fields on the model plus\ncross-field rules (BAA addon, DPA mode, uniqueness). The view supplies the\norganization and submitting user.'
    )
