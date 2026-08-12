import { ContainerModule } from "inversify";
import { SUSPENSION_SERVICE } from "./identifiers";
import { SuspensionService } from "./suspension";

export const suspensionModule = new ContainerModule(({ bind }) => {
  bind(SUSPENSION_SERVICE).to(SuspensionService).inSingletonScope();
});
