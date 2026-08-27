import { CONTRIBUTION } from "@posthog/di/contribution";
import { ContainerModule } from "inversify";
import { WorkspaceEventsContribution } from "./workspace-events.contribution";

export const workspaceUiModule = new ContainerModule(({ bind }) => {
  bind(CONTRIBUTION).to(WorkspaceEventsContribution).inSingletonScope();
});
