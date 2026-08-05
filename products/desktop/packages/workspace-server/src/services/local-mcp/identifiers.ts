import type { LocalMcpServerDescriptor } from "@posthog/shared";
import type { AddUserMcpServerInput } from "./schemas";

export const LOCAL_MCP_SERVICE = Symbol.for("posthog.workspace.localMcp");

export interface LocalMcpService {
  /**
   * Lists the user's locally configured MCP servers (~/.claude.json), merging
   * the project-scoped section for `cwd` over the user-scoped one when given.
   */
  listServers(cwd?: string): Promise<LocalMcpServerDescriptor[]>;
  /**
   * Adds or replaces a user-scoped streamable-HTTP server in ~/.claude.json,
   * the same entry `claude mcp add --scope user --transport http` writes.
   */
  addUserServer(input: AddUserMcpServerInput): Promise<void>;
}
