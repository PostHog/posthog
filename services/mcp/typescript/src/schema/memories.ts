import { z } from 'zod'

export const MemoryMetadataSchema = z.record(z.any()).optional()

export const AgentMemorySchema = z.object({
    id: z.string().uuid(),
    contents: z.string(),
    metadata: z.record(z.any()),
    user_id: z.number().nullable(),
    created_at: z.string(),
    updated_at: z.string(),
})
export type AgentMemory = z.infer<typeof AgentMemorySchema>

export const CreateMemoryInputSchema = z.object({
    contents: z.string().describe('The content of the memory to store'),
    metadata: z.record(z.any()).optional().describe('Optional metadata tags for the memory'),
})
export type CreateMemoryInput = z.infer<typeof CreateMemoryInputSchema>

export const QueryMemoryInputSchema = z.object({
    query_text: z.string().describe('The search query for finding relevant memories'),
    metadata_filter: z.record(z.any()).optional().describe('Filter by metadata key-value pairs'),
    user_only: z.boolean().default(true).describe('Search only current user memories, or all team memories'),
    limit: z.number().default(10).describe('Maximum number of results to return'),
})
export type QueryMemoryInput = z.infer<typeof QueryMemoryInputSchema>

export const UpdateMemoryInputSchema = z.object({
    contents: z.string().optional().describe('New content for the memory'),
    metadata: z.record(z.any()).optional().describe('New metadata for the memory'),
})
export type UpdateMemoryInput = z.infer<typeof UpdateMemoryInputSchema>

export const MemoryQueryResultSchema = z.object({
    memory_id: z.string(),
    contents: z.string(),
    metadata: z.record(z.any()),
    distance: z.number(),
})
export type MemoryQueryResult = z.infer<typeof MemoryQueryResultSchema>

export const MemoryQueryResponseSchema = z.object({
    results: z.array(MemoryQueryResultSchema),
    count: z.number(),
})
export type MemoryQueryResponse = z.infer<typeof MemoryQueryResponseSchema>

export const MetadataKeysResponseSchema = z.object({
    keys: z.array(z.string()),
})
export type MetadataKeysResponse = z.infer<typeof MetadataKeysResponseSchema>
