import { ContainerModule } from "inversify";
import { ONBOARDING_IMPORT_SERVICE } from "./identifiers";
import { OnboardingImportServiceImpl } from "./onboarding-import";

export const onboardingImportModule = new ContainerModule(({ bind }) => {
  bind(ONBOARDING_IMPORT_SERVICE)
    .to(OnboardingImportServiceImpl)
    .inSingletonScope();
});
