import { ContainerModule } from "inversify";
import { ClaudeCliSessionsServiceImpl } from "./claude-cli-sessions";
import {
  CLAUDE_CLI_SESSIONS_SERVICE,
  IMPORTED_SESSION_CLEANER,
} from "./identifiers";

export const claudeCliSessionsModule = new ContainerModule(({ bind }) => {
  bind(CLAUDE_CLI_SESSIONS_SERVICE)
    .to(ClaudeCliSessionsServiceImpl)
    .inSingletonScope();
  // Alias the narrow cleaner contract to the same singleton, so the workspace
  // and archive services can compensate a deleted task without the full service.
  bind(IMPORTED_SESSION_CLEANER).toService(CLAUDE_CLI_SESSIONS_SERVICE);
});
