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

export const groupApiGroupTypeIndexMin = -2147483648
export const groupApiGroupTypeIndexMax = 2147483647

export const groupApiGroupKeyMax = 400

export const GroupApi = zod.object({
    group_type_index: zod.number().min(groupApiGroupTypeIndexMin).max(groupApiGroupTypeIndexMax),
    group_key: zod.string().max(groupApiGroupKeyMax),
    group_properties: zod.unknown().optional(),
    created_at: zod.iso.datetime({ offset: true }),
})

export type GroupApi = zod.input<typeof GroupApi>
export type GroupApiOutput = zod.output<typeof GroupApi>

export const createGroupApiGroupTypeIndexMin = -2147483648
export const createGroupApiGroupTypeIndexMax = 2147483647

export const createGroupApiGroupKeyMax = 400

export const CreateGroupApi = zod.object({
    group_type_index: zod.number().min(createGroupApiGroupTypeIndexMin).max(createGroupApiGroupTypeIndexMax),
    group_key: zod.string().max(createGroupApiGroupKeyMax),
    group_properties: zod.unknown().optional(),
})

export type CreateGroupApi = zod.input<typeof CreateGroupApi>
export type CreateGroupApiOutput = zod.output<typeof CreateGroupApi>
