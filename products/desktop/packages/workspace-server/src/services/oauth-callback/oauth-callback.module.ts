import { ContainerModule } from "inversify";
import { OAUTH_CALLBACK_SERVER } from "./identifiers";
import { OAuthCallbackServer } from "./oauth-callback";

export const oauthCallbackModule = new ContainerModule(({ bind }) => {
  bind(OAUTH_CALLBACK_SERVER).to(OAuthCallbackServer).inSingletonScope();
});
