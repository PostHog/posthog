import { ContainerModule } from "inversify";
import { SKETCHPAD_CACHE_SERVICE } from "./identifiers";
import { SketchpadCacheServiceImpl } from "./sketchpadCacheService";

export const sketchpadCacheModule = new ContainerModule(({ bind }) => {
  bind(SKETCHPAD_CACHE_SERVICE)
    .to(SketchpadCacheServiceImpl)
    .inSingletonScope();
});
