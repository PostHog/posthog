import { readFileSync } from "node:fs";
import { normalizeGatewayModelsResponse } from "@posthog/shared";
import { beforeEach } from "vitest";

const SAVED_GATEWAY_LISTING: unknown = JSON.parse(
  readFileSync(
    new URL(
      "../../../../../tasks/backend/tests/fixtures/gateway_models.json",
      import.meta.url,
    ),
    "utf8",
  ),
);

beforeEach(() => {
  normalizeGatewayModelsResponse(SAVED_GATEWAY_LISTING);
});
