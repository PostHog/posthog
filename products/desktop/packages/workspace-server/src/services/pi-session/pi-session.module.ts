import { ContainerModule } from "inversify";
import { PI_SESSION_SERVICE } from "./identifiers";
import { PiSessionService } from "./pi-session";

export const piSessionModule = new ContainerModule(({ bind }) => {
  bind(PI_SESSION_SERVICE).to(PiSessionService).inSingletonScope();
});
