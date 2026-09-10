import { ContainerModule } from "inversify";
import { EnrichmentService } from "./enrichment";
import { ENRICHMENT_SERVICE } from "./identifiers";

export const enrichmentModule = new ContainerModule(({ bind }) => {
  bind(ENRICHMENT_SERVICE).to(EnrichmentService).inSingletonScope();
});
