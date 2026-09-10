import { loadUserClaudeJsonMcpServerDescriptors } from "@posthog/agent/adapters/claude/session/mcp-config";
import type { LocalMcpServerDescriptor } from "@posthog/shared";
import { injectable } from "inversify";
import type { LocalMcpService } from "./identifiers";

@injectable()
export class LocalMcpServiceImpl implements LocalMcpService {
  async listServers(cwd?: string): Promise<LocalMcpServerDescriptor[]> {
    return loadUserClaudeJsonMcpServerDescriptors(cwd);
  }
}
