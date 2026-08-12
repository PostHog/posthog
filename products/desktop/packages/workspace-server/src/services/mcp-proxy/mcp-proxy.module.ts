import { ContainerModule } from "inversify";
import { MCP_PROXY_SERVICE } from "./identifiers";
import { McpProxyService } from "./mcp-proxy";

export const mcpProxyModule = new ContainerModule(({ bind }) => {
  bind(MCP_PROXY_SERVICE).to(McpProxyService).inSingletonScope();
});
