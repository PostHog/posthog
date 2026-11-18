import { z } from "zod";

export const claudeSubscriptionTokenInput = z.object({
  token: z
    .string()
    .trim()
    .max(4096)
    .regex(/^sk-ant-oat01-\S{29,}$/),
});
