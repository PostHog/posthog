import { ContainerModule } from "inversify";
import { AgentService } from "./agent";
import { AgentAuthAdapter } from "./auth-adapter";
import {
  AGENT_AUTH_ADAPTER,
  AGENT_SERVICE,
  MCP_SERVER_CONNECTION_SOURCE,
  MCP_TOOL_POLICY_UPDATER,
} from "./identifiers";

export const agentModule = new ContainerModule(({ bind }) => {
  bind(AGENT_SERVICE).to(AgentService).inSingletonScope();
  bind(AGENT_AUTH_ADAPTER).to(AgentAuthAdapter).inSingletonScope();
  bind(MCP_SERVER_CONNECTION_SOURCE).toService(AGENT_AUTH_ADAPTER);
  bind(MCP_TOOL_POLICY_UPDATER).toService(AGENT_AUTH_ADAPTER);
});
