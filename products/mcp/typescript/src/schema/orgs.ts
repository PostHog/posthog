import { z } from 'zod'

export const OrganizationSchema = z.object({
    id: z.string().uuid(),
    name: z.string(),
})

export type Organization = z.infer<typeof OrganizationSchema>
