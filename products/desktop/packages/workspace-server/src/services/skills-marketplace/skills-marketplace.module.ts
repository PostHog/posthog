import { ContainerModule } from "inversify";
import { SKILLS_MARKETPLACE_SERVICE } from "./identifiers";
import { SkillsMarketplaceService } from "./skills-marketplace";

export const skillsMarketplaceModule = new ContainerModule(({ bind }) => {
  bind(SKILLS_MARKETPLACE_SERVICE)
    .to(SkillsMarketplaceService)
    .inSingletonScope();
});
