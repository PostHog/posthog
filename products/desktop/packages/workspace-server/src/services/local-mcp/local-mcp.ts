import {
  loadUserClaudeJsonMcpServerDescriptors,
  saveUserClaudeJsonHttpMcpServer,
} from "@posthog/agent/adapters/claude/session/mcp-config";
import type { LocalMcpServerDescriptor } from "@posthog/shared";
import { injectable } from "inversify";
import type { LocalMcpService } from "./identifiers";
import type { AddUserMcpServerInput } from "./schemas";

@injectable()
export class LocalMcpServiceImpl implements LocalMcpService {
  async listServers(cwd?: string): Promise<LocalMcpServerDescriptor[]> {
    return loadUserClaudeJsonMcpServerDescriptors(cwd);
  }

  async addUserServer(input: AddUserMcpServerInput): Promise<void> {
    saveUserClaudeJsonHttpMcpServer(input.name, input.url);
  }
}
