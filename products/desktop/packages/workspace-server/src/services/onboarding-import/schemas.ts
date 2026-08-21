import { z } from "zod";

const category = z.object({
  count: z.number(),
  paths: z.array(z.string()),
});

export const summaryOutput = z.object({
  total: z.number(),
  skills: category,
  plugins: category,
  mcpServers: category,
  permissions: category,
});

export type OnboardingImportSummary = z.infer<typeof summaryOutput>;
