import { ContainerModule } from "inversify";
import { CanvasV2CacheServiceImpl } from "./canvasV2CacheService";
import { CANVAS_V2_CACHE_SERVICE } from "./identifiers";

export const canvasV2CacheModule = new ContainerModule(({ bind }) => {
  bind(CANVAS_V2_CACHE_SERVICE).to(CanvasV2CacheServiceImpl).inSingletonScope();
});
