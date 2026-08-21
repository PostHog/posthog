import { ContainerModule } from "inversify";
import { ExternalAppsService } from "./external-apps";
import { EXTERNAL_APPS_SERVICE } from "./identifiers";

export const externalAppsModule = new ContainerModule(({ bind }) => {
  bind(EXTERNAL_APPS_SERVICE).to(ExternalAppsService).inSingletonScope();
});
