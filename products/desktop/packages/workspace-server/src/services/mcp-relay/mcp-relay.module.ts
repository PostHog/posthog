import { ContainerModule } from "inversify";
import { MCP_RELAY_SERVICE } from "./identifiers";
import { McpRelayServiceImpl } from "./mcp-relay";

export const mcpRelayModule = new ContainerModule(({ bind }) => {
  bind(MCP_RELAY_SERVICE).to(McpRelayServiceImpl).inSingletonScope();
});
