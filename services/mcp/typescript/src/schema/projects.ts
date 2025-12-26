import { z } from 'zod'

export const ProjectSchema = z.object({
    id: z.number(),
    name: z.string(),
    organization: z.string().uuid(),
})

export type Project = z.infer<typeof ProjectSchema>
