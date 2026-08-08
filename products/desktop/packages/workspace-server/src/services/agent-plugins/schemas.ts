import { z } from "zod";

export const AGENT_PLUGINS_MANIFEST_SCHEMA =
  "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json";
export const AGENT_PLUGINS_MCP_SCHEMA =
  "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json";
export const AGENT_PLUGIN_INSTALLATION_ID_PATTERN = /^[a-f0-9]{16}$/;

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

export const agentPluginHttpMcpServer = z.object({
  name: z.string(),
  type: z.literal("streamable-http"),
  url: z.string(),
  headers: z.record(z.string(), z.string()).optional(),
});

export const agentPluginMcpServerSummary = z.object({
  name: z.string(),
  type: z.enum(["streamable-http", "stdio", "sse"]),
});

export const agentPluginPreview = z.object({
  valid: z.boolean(),
  sourcePath: z.string(),
  manifest: agentPluginManifest.nullable(),
  skills: z.array(agentPluginSkill),
  mcpServers: z.array(agentPluginMcpServerSummary),
  diagnostics: z.array(agentPluginDiagnostic),
  selectionToken: z.string().uuid().optional(),
});

export const agentPluginInstallation = z.object({
  id: z.string().regex(AGENT_PLUGIN_INSTALLATION_ID_PATTERN),
  sourcePath: z.string(),
  enabled: z.boolean(),
  manifest: agentPluginManifest,
  skills: z.array(agentPluginSkill),
  mcpServers: z.array(agentPluginMcpServerSummary),
  diagnostics: z.array(agentPluginDiagnostic),
});

export const listAgentPluginsOutput = z.array(agentPluginInstallation);
export const selectAgentPluginOutput = agentPluginPreview.nullable();
export const registerAgentPluginInput = z.object({
  selectionToken: z.string().uuid(),
});
export const agentPluginIdInput = z.object({
  id: z.string().regex(AGENT_PLUGIN_INSTALLATION_ID_PATTERN),
});
export const setAgentPluginEnabledInput = z.object({
  id: z.string().regex(AGENT_PLUGIN_INSTALLATION_ID_PATTERN),
  enabled: z.boolean(),
});

export const agentPluginState = z.object({
  version: z.literal(1),
  installations: z.array(
    agentPluginInstallation.extend({
      id: z.string().regex(AGENT_PLUGIN_INSTALLATION_ID_PATTERN),
      mcpServers: z.array(agentPluginMcpServerSummary).default([]),
    }),
  ),
});

export type AgentPluginDiagnostic = z.infer<typeof agentPluginDiagnostic>;
export type AgentPluginManifest = z.infer<typeof agentPluginManifest>;
export type AgentPluginSkill = z.infer<typeof agentPluginSkill>;
export type AgentPluginHttpMcpServer = z.infer<typeof agentPluginHttpMcpServer>;
export type AgentPluginMcpServerSummary = z.infer<
  typeof agentPluginMcpServerSummary
>;
export type AgentPluginPreview = z.infer<typeof agentPluginPreview>;
export type AgentPluginInstallation = z.infer<typeof agentPluginInstallation>;
export type AgentPluginPersistedInstallation = z.infer<
  typeof agentPluginState
>["installations"][number];

export interface LoadedAgentPlugin {
  valid: boolean;
  sourcePath: string;
  manifest: AgentPluginManifest | null;
  skills: AgentPluginSkill[];
  mcpServers: AgentPluginHttpMcpServer[];
  diagnostics: AgentPluginDiagnostic[];
}
