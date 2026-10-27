import { z } from "zod";

export const claudeSubscriptionAccountInput = z.object({
  expectedAccountKey: z.string().min(1).optional(),
});

export const claudeSubscriptionTokenInput =
  claudeSubscriptionAccountInput.extend({
    token: z
      .string()
      .trim()
      .max(4096)
      .regex(/^sk-ant-oat01-\S{29,}$/),
  });
