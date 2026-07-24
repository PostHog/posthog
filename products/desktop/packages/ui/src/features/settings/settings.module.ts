import { CONTRIBUTION } from "@posthog/di/contribution";
import { ContainerModule } from "inversify";
import { CustomInstructionsSyncContribution } from "./customInstructionsSync.contribution";

export const settingsUiModule = new ContainerModule(({ bind }) => {
  bind(CONTRIBUTION).to(CustomInstructionsSyncContribution).inSingletonScope();
});
