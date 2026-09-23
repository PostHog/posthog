import {
  SETTINGS_BACKUP_SERVICE,
  SETTINGS_BACKUP_STATE,
  SettingsBackupService,
} from "@posthog/core/settings/settingsBackup";
import { CONTRIBUTION } from "@posthog/di/contribution";
import { ContainerModule } from "inversify";
import { CustomInstructionsSyncContribution } from "./customInstructionsSync.contribution";
import { settingsBackupState } from "./settingsBackupState";

export const settingsUiModule = new ContainerModule(({ bind }) => {
  bind(SETTINGS_BACKUP_STATE).toConstantValue(settingsBackupState);
  bind(SETTINGS_BACKUP_SERVICE).to(SettingsBackupService).inSingletonScope();
  bind(CONTRIBUTION).to(CustomInstructionsSyncContribution).inSingletonScope();
});
