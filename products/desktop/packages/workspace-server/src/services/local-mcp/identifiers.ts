import type { LocalMcpServerDescriptor } from "@posthog/shared";

export const LOCAL_MCP_SERVICE = Symbol.for("posthog.workspace.localMcp");

export interface LocalMcpService {
  /**
   * Lists the user's locally configured MCP servers (~/.claude.json), merging
   * the project-scoped section for `cwd` over the user-scoped one when given.
   */
  listServers(cwd?: string): Promise<LocalMcpServerDescriptor[]>;
}
