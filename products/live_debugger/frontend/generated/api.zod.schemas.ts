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

export const liveDebuggerBreakpointApiLineNumberMin = 0
export const liveDebuggerBreakpointApiLineNumberMax = 2147483647

export const LiveDebuggerBreakpointApi = zod.object({
    id: zod.uuid(),
    repository: zod.string().nullish(),
    filename: zod.string(),
    line_number: zod.number().min(liveDebuggerBreakpointApiLineNumberMin).max(liveDebuggerBreakpointApiLineNumberMax),
    enabled: zod.boolean().optional(),
    condition: zod.string().nullish(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
})

export type LiveDebuggerBreakpointApi = zod.input<typeof LiveDebuggerBreakpointApi>
export type LiveDebuggerBreakpointApiOutput = zod.output<typeof LiveDebuggerBreakpointApi>

export const PaginatedLiveDebuggerBreakpointListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(LiveDebuggerBreakpointApi),
})

export type PaginatedLiveDebuggerBreakpointListApi = zod.input<typeof PaginatedLiveDebuggerBreakpointListApi>
export type PaginatedLiveDebuggerBreakpointListApiOutput = zod.output<typeof PaginatedLiveDebuggerBreakpointListApi>

export const patchedLiveDebuggerBreakpointApiLineNumberMin = 0
export const patchedLiveDebuggerBreakpointApiLineNumberMax = 2147483647

export const PatchedLiveDebuggerBreakpointApi = zod.object({
    id: zod.uuid().optional(),
    repository: zod.string().nullish(),
    filename: zod.string().optional(),
    line_number: zod
        .number()
        .min(patchedLiveDebuggerBreakpointApiLineNumberMin)
        .max(patchedLiveDebuggerBreakpointApiLineNumberMax)
        .optional(),
    enabled: zod.boolean().optional(),
    condition: zod.string().nullish(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
})

export type PatchedLiveDebuggerBreakpointApi = zod.input<typeof PatchedLiveDebuggerBreakpointApi>
export type PatchedLiveDebuggerBreakpointApiOutput = zod.output<typeof PatchedLiveDebuggerBreakpointApi>

export const ActiveBreakpointApi = zod
    .object({
        id: zod.uuid().describe('Unique identifier for the breakpoint'),
        repository: zod.string().nullish().describe("Repository identifier (e.g., 'PostHog\/posthog')"),
        filename: zod.string().describe('File path where the breakpoint is set'),
        line_number: zod.number().describe('Line number of the breakpoint'),
        enabled: zod.boolean().describe('Whether the breakpoint is enabled'),
        condition: zod.string().nullish().describe('Optional condition for the breakpoint'),
    })
    .describe('Schema for a single active breakpoint')

export type ActiveBreakpointApi = zod.input<typeof ActiveBreakpointApi>
export type ActiveBreakpointApiOutput = zod.output<typeof ActiveBreakpointApi>

export const ActiveBreakpointsResponseApi = zod
    .object({
        breakpoints: zod.array(ActiveBreakpointApi).describe('List of active breakpoints'),
    })
    .describe('Response schema for active breakpoints endpoint')

export type ActiveBreakpointsResponseApi = zod.input<typeof ActiveBreakpointsResponseApi>
export type ActiveBreakpointsResponseApiOutput = zod.output<typeof ActiveBreakpointsResponseApi>

export const BreakpointHitApi = zod
    .object({
        id: zod.uuid().describe('Unique identifier for the hit event'),
        lineNumber: zod.number().describe('Line number where the breakpoint was hit'),
        functionName: zod.string().describe('Name of the function where breakpoint was hit'),
        timestamp: zod.iso.datetime({ offset: true }).describe('When the breakpoint was hit'),
        variables: zod.record(zod.string(), zod.unknown()).describe('Local variables at the time of the hit'),
        stackTrace: zod.array(zod.unknown()).describe('Stack trace at the time of the hit'),
        breakpoint_id: zod.uuid().describe('ID of the breakpoint that was hit'),
        filename: zod.string().describe('Filename where the breakpoint was hit'),
    })
    .describe('Schema for a single breakpoint hit event')

export type BreakpointHitApi = zod.input<typeof BreakpointHitApi>
export type BreakpointHitApiOutput = zod.output<typeof BreakpointHitApi>

export const BreakpointHitsResponseApi = zod
    .object({
        results: zod.array(BreakpointHitApi).describe('List of breakpoint hit events'),
        count: zod.number().describe('Number of results returned'),
        has_more: zod.boolean().describe('Whether there are more results available'),
    })
    .describe('Response schema for breakpoint hits endpoint')

export type BreakpointHitsResponseApi = zod.input<typeof BreakpointHitsResponseApi>
export type BreakpointHitsResponseApiOutput = zod.output<typeof BreakpointHitsResponseApi>
