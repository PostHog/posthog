import { ContainerModule } from "inversify";
import { SHELL_SERVICE } from "./identifiers";
import { ShellService } from "./shell";

export const shellModule = new ContainerModule(({ bind }) => {
  bind(SHELL_SERVICE).to(ShellService).inSingletonScope();
});
