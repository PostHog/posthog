import { ContainerModule } from "inversify";
import { PROCESS_TRACKING_SERVICE } from "./identifiers";
import { ProcessTrackingService } from "./process-tracking";

export const processTrackingModule = new ContainerModule(({ bind }) => {
  bind(PROCESS_TRACKING_SERVICE).to(ProcessTrackingService).inSingletonScope();
});
