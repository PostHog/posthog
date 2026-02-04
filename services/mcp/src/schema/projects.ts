import { z } from 'zod'

export const ProjectSchema = z.object({
    id: z.number(),
    name: z.string(),
    organization: z.string().uuid(),
    api_token: z.string(),
})

export type Project = z.infer<typeof ProjectSchema>
