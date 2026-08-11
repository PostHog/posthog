export const MCP_RELAY_SERVICE = Symbol.for("posthog.workspace.mcpRelay");

export interface McpRelayExecution {
  /** Verbatim JSON-RPC response from the local server (absent for notifications). */
  payload?: Record<string, unknown>;
  /** Desktop-side failure (unknown server, spawn failure, timeout, oversized response). */
  error?: { code: number; message: string };
}

export interface McpRelayService {
  /**
   * Executes one relayed JSON-RPC message against the named local MCP server,
   * lazily opening (and caching) a real connection per `(runId, server)`.
   */
  execute(
    runId: string,
    server: string,
    payload: Record<string, unknown>,
  ): Promise<McpRelayExecution>;

  /** Closes and drops every relay connection owned by the run. */
  closeRun(runId: string): Promise<void>;
}
