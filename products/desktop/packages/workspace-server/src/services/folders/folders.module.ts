import { ContainerModule } from "inversify";
import { FoldersService } from "./folders";
import { FOLDERS_SERVICE } from "./identifiers";

export const foldersModule = new ContainerModule(({ bind }) => {
  bind(FOLDERS_SERVICE).to(FoldersService).inSingletonScope();
});
