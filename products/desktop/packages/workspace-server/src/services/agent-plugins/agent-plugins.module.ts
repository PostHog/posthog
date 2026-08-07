import { ContainerModule } from "inversify";
import { AgentPluginsService } from "./agent-plugins";
import { AGENT_PLUGINS_SERVICE } from "./identifiers";

export const agentPluginsModule = new ContainerModule(({ bind }) => {
  bind(AGENT_PLUGINS_SERVICE).to(AgentPluginsService).inSingletonScope();
});
