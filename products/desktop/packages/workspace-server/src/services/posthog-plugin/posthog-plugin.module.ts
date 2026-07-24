import { ContainerModule } from "inversify";
import { POSTHOG_PLUGIN_SERVICE } from "./identifiers";
import { PosthogPluginService } from "./posthog-plugin";

export const posthogPluginModule = new ContainerModule(({ bind }) => {
  bind(POSTHOG_PLUGIN_SERVICE).to(PosthogPluginService).inSingletonScope();
});
