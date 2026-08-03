import { ContainerModule } from "inversify";
import { AgentService } from "./agent";
import { AgentAuthAdapter } from "./auth-adapter";
import { AGENT_AUTH_ADAPTER, AGENT_SERVICE } from "./identifiers";

export const agentModule = new ContainerModule(({ bind }) => {
  bind(AGENT_SERVICE).to(AgentService).inSingletonScope();
  bind(AGENT_AUTH_ADAPTER).to(AgentAuthAdapter).inSingletonScope();
});
