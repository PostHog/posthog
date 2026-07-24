import { ContainerModule } from "inversify";
import { ArchiveService } from "./archive";
import { ARCHIVE_SERVICE } from "./identifiers";

export const archiveModule = new ContainerModule(({ bind }) => {
  bind(ARCHIVE_SERVICE).to(ArchiveService).inSingletonScope();
});
