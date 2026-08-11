import { ContainerModule } from "inversify";
import { RELEASE_FEED_SERVICE } from "./identifiers";
import { ReleaseFeedService } from "./release-feed";

export const releaseFeedModule = new ContainerModule(({ bind }) => {
  bind(RELEASE_FEED_SERVICE).to(ReleaseFeedService).inSingletonScope();
});
