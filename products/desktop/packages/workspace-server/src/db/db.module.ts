import { ContainerModule } from "inversify";
import { DATABASE_SERVICE } from "./identifiers";
import { DatabaseService } from "./service";

export const databaseModule = new ContainerModule(({ bind }) => {
  bind(DATABASE_SERVICE).to(DatabaseService).inSingletonScope();
});
