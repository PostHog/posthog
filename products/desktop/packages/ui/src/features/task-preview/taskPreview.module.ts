import { CONTRIBUTION } from "@posthog/di/contribution";
import { ContainerModule } from "inversify";
import { TaskBrowserContribution } from "./taskBrowser.contribution";
import { TaskPreviewPortsContribution } from "./taskPreviewPorts.contribution";

export const taskPreviewUiModule = new ContainerModule(({ bind }) => {
  bind(CONTRIBUTION).to(TaskBrowserContribution).inSingletonScope();
  bind(CONTRIBUTION).to(TaskPreviewPortsContribution).inSingletonScope();
});
