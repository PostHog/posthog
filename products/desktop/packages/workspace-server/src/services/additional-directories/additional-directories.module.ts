import { ContainerModule } from "inversify";
import { AdditionalDirectoriesService } from "./additional-directories";
import { ADDITIONAL_DIRECTORIES_SERVICE } from "./identifiers";

export const additionalDirectoriesModule = new ContainerModule(({ bind }) => {
  bind(ADDITIONAL_DIRECTORIES_SERVICE)
    .to(AdditionalDirectoriesService)
    .inSingletonScope();
});
