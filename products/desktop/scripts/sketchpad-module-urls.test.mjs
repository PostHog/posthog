import assert from "node:assert/strict";
import { test } from "node:test";
import { pinSketchpadModuleUrl } from "./sketchpad-module-urls.mjs";

test("pins range shims while preserving subpaths and query options", () => {
  assert.equal(
    pinSketchpadModuleUrl(
      "https://esm.sh/@floating-ui/utils@%5E0.2.11/dom?target=es2022",
      "/@floating-ui/utils@0.2.12/es2022/dom.mjs",
    ),
    "https://esm.sh/@floating-ui/utils@0.2.12/dom?target=es2022",
  );
  assert.equal(
    pinSketchpadModuleUrl("https://esm.sh/react@19.0.0", null),
    "https://esm.sh/react@19.0.0",
  );
  for (const resolved of [
    null,
    "/other@1.0.0/mod.mjs",
    "/react@latest/mod.mjs",
  ]) {
    assert.throws(
      () => pinSketchpadModuleUrl("https://esm.sh/react@%5E19", resolved),
      /Cannot pin/,
    );
  }
});
