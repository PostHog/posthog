import { ContainerModule } from "inversify";
import { BROWSER_TABS_SERVICE } from "../../di/tokens";
import { BrowserTabsService } from "./service";

export const browserTabsModule = new ContainerModule(({ bind }) => {
  bind(BROWSER_TABS_SERVICE).to(BrowserTabsService).inSingletonScope();
});
