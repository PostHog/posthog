import { ContainerModule } from "inversify";
import { AuthProxyService } from "./auth-proxy";
import { AUTH_PROXY_SERVICE } from "./identifiers";

export const authProxyModule = new ContainerModule(({ bind }) => {
  bind(AUTH_PROXY_SERVICE).to(AuthProxyService).inSingletonScope();
});
