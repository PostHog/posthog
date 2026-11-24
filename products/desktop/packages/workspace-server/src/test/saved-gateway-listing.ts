import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { normalizeGatewayModelsResponse } from "@posthog/shared";
import { beforeEach } from "vitest";

const SAVED_GATEWAY_LISTING: unknown = JSON.parse(
  readFileSync(
    resolve(
      __dirname,
      "../../../../../../packages/agent/packages/agent-contracts/testing/gateway-models.json",
    ),
    "utf8",
  ),
);

beforeEach(() => {
  normalizeGatewayModelsResponse(SAVED_GATEWAY_LISTING);
});
