import { ContainerModule } from "inversify";
import { WATCHER_REGISTRY_SERVICE } from "./identifiers";
import { WatcherRegistryService } from "./watcher-registry";

export const watcherRegistryModule = new ContainerModule(({ bind }) => {
  bind(WATCHER_REGISTRY_SERVICE).to(WatcherRegistryService).inSingletonScope();
});
