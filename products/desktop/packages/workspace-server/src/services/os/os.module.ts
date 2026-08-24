import { ContainerModule } from "inversify";
import { OS_SERVICE } from "./identifiers";
import { OsService } from "./os";

export const osModule = new ContainerModule(({ bind }) => {
  bind(OS_SERVICE).to(OsService).inSingletonScope();
});
