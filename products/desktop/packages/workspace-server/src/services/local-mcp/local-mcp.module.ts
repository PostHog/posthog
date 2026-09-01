import { ContainerModule } from "inversify";
import { LOCAL_MCP_SERVICE } from "./identifiers";
import { LocalMcpServiceImpl } from "./local-mcp";

export const localMcpModule = new ContainerModule(({ bind }) => {
  bind(LOCAL_MCP_SERVICE).to(LocalMcpServiceImpl).inSingletonScope();
});
