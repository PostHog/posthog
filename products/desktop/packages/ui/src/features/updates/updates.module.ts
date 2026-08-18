import { CONTRIBUTION } from "@posthog/di/contribution";
import { ContainerModule } from "inversify";
import { DeferredInstallContribution } from "./deferred-install.contribution";

export const updatesUiModule = new ContainerModule(({ bind }) => {
  bind(CONTRIBUTION).to(DeferredInstallContribution).inSingletonScope();
});
