import { ContainerModule } from "inversify";
import { WORKSPACE_SERVICE } from "./identifiers";
import { WorkspaceService } from "./workspace";

export const workspaceModule = new ContainerModule(({ bind }) => {
  bind(WORKSPACE_SERVICE).to(WorkspaceService).inSingletonScope();
});
