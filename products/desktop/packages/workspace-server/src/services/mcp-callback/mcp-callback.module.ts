import { ContainerModule } from "inversify";
import { MCP_CALLBACK_SERVER, MCP_CALLBACK_SERVICE } from "./identifiers";
import { McpCallbackService } from "./mcp-callback";
import { McpCallbackServer } from "./mcp-callback-server";

export const mcpCallbackModule = new ContainerModule(({ bind }) => {
  bind(MCP_CALLBACK_SERVER).to(McpCallbackServer).inSingletonScope();
  bind(MCP_CALLBACK_SERVICE).to(McpCallbackService).inSingletonScope();
});
