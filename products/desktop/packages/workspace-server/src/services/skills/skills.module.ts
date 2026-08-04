import { ContainerModule } from "inversify";
import { WATCHER_SERVICE } from "../../di/tokens";
import { WatcherService } from "../watcher/service";
import { SKILLS_SERVICE } from "./identifiers";
import { SkillsService } from "./skills";

export const skillsModule = new ContainerModule(({ bind }) => {
  bind(SKILLS_SERVICE).to(SkillsService).inSingletonScope();
  // SkillsService watches the writable skill roots. Hosts that load this
  // module (Electron main) do not otherwise bind WatcherService.
  bind(WATCHER_SERVICE).to(WatcherService).inSingletonScope();
});
