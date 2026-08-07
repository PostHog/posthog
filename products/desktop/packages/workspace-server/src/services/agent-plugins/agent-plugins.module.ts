import { ContainerModule } from "inversify";
import { AgentPluginsService } from "./agent-plugins";
import { AgentPluginHttpProxyService } from "./http-proxy";
import {
  AGENT_PLUGIN_HTTP_PROXY,
  AGENT_PLUGIN_STDIO_BRIDGE,
  AGENT_PLUGINS_SERVICE,
} from "./identifiers";
import { AgentPluginStdioBridgeService } from "./stdio-bridge";

export const agentPluginsModule = new ContainerModule(({ bind }) => {
  bind(AGENT_PLUGIN_HTTP_PROXY)
    .to(AgentPluginHttpProxyService)
    .inSingletonScope();
  bind(AGENT_PLUGIN_STDIO_BRIDGE)
    .to(AgentPluginStdioBridgeService)
    .inSingletonScope();
  bind(AGENT_PLUGINS_SERVICE).to(AgentPluginsService).inSingletonScope();
});
