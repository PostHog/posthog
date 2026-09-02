import { ContainerModule } from "inversify";
import { WORKSPACE_METADATA_SERVICE } from "./identifiers";
import { WorkspaceMetadataService } from "./workspace-metadata";

export const workspaceMetadataModule = new ContainerModule(({ bind }) => {
  bind(WORKSPACE_METADATA_SERVICE)
    .to(WorkspaceMetadataService)
    .inSingletonScope();
});
