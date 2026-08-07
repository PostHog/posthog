import { z } from "zod";

export const AGENT_PLUGINS_MANIFEST_SCHEMA =
  "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json";

export const agentPluginDiagnostic = z.object({
  severity: z.enum(["warning", "error"]),
  code: z.string(),
  message: z.string(),
  path: z.string().optional(),
});

export const agentPluginManifest = z.object({
  $schema: z.literal(AGENT_PLUGINS_MANIFEST_SCHEMA),
  name: z.string(),
  version: z.string().optional(),
  description: z.string().optional(),
  author: z
    .object({
      name: z.string().optional(),
      email: z.string().optional(),
      url: z.string().optional(),
    })
    .optional(),
  homepage: z.string().optional(),
  repository: z.string().optional(),
  license: z.string().optional(),
  keywords: z.array(z.string()).optional(),
});

export const agentPluginSkill = z.object({
  name: z.string(),
  description: z.string(),
  path: z.string(),
});

export const agentPluginPreview = z.object({
  valid: z.boolean(),
  sourcePath: z.string(),
  manifest: agentPluginManifest.nullable(),
  skills: z.array(agentPluginSkill),
  diagnostics: z.array(agentPluginDiagnostic),
});

export const agentPluginInstallation = z.object({
  id: z.string(),
  sourcePath: z.string(),
  enabled: z.boolean(),
  manifest: agentPluginManifest,
  skills: z.array(agentPluginSkill),
  diagnostics: z.array(agentPluginDiagnostic),
});

export const listAgentPluginsOutput = z.array(agentPluginInstallation);
export const previewAgentPluginInput = z.object({ sourcePath: z.string() });
export const selectAgentPluginOutput = agentPluginPreview.nullable();
export const registerAgentPluginInput = z.object({ sourcePath: z.string() });
export const agentPluginIdInput = z.object({ id: z.string() });
export const setAgentPluginEnabledInput = z.object({
  id: z.string(),
  enabled: z.boolean(),
});

export const agentPluginState = z.object({
  version: z.literal(1),
  installations: z.array(
    z.object({
      id: z.string(),
      sourcePath: z.string(),
      enabled: z.boolean(),
      manifest: agentPluginManifest,
      skills: z.array(agentPluginSkill),
      diagnostics: z.array(agentPluginDiagnostic),
    }),
  ),
});

export type AgentPluginDiagnostic = z.infer<typeof agentPluginDiagnostic>;
export type AgentPluginManifest = z.infer<typeof agentPluginManifest>;
export type AgentPluginSkill = z.infer<typeof agentPluginSkill>;
export type AgentPluginPreview = z.infer<typeof agentPluginPreview>;
export type AgentPluginInstallation = z.infer<typeof agentPluginInstallation>;
