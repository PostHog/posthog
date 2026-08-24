import { z } from "zod";

const CURRENT_SCHEMA_VERSION = 1;

const setupSchema = z.object({
  script: z.string().optional(),
});

export const environmentActionSchema = z.object({
  name: z.string().min(1),
  icon: z.string().optional(),
  command: z.string().min(1),
});

export const environmentSchema = z.object({
  id: z.string(),
  version: z.literal(CURRENT_SCHEMA_VERSION),
  name: z.string().min(1),
  setup: setupSchema.optional(),
  actions: z.array(environmentActionSchema).optional(),
});

const repoPathInput = z.object({
  repoPath: z.string().min(1),
});

const repoPathWithIdInput = repoPathInput.extend({
  id: z.string(),
});

export const listEnvironmentsInput = repoPathInput;

export const getEnvironmentInput = repoPathWithIdInput;

export const deleteEnvironmentInput = repoPathWithIdInput;

export const createEnvironmentInput = repoPathInput.extend({
  name: z.string().min(1),
  setup: setupSchema.optional(),
  actions: z.array(environmentActionSchema).optional(),
});

export const updateEnvironmentInput = repoPathWithIdInput.extend({
  name: z.string().min(1).optional(),
  setup: setupSchema.optional(),
  actions: z.array(environmentActionSchema).optional(),
});

export type Environment = z.infer<typeof environmentSchema>;
export type EnvironmentAction = z.infer<typeof environmentActionSchema>;
export type CreateEnvironmentInput = z.infer<typeof createEnvironmentInput>;
export type UpdateEnvironmentInput = z.infer<typeof updateEnvironmentInput>;

export function slugifyEnvironmentName(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}
