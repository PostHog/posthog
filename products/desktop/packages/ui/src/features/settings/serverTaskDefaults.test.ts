import { describe, expect, it } from "vitest";
import { nextTaskDefaultsSync } from "./serverTaskDefaults";

const UNSET = { start_in_plan_mode: null, auto_publish_cloud_runs: null };

describe("serverTaskDefaults", () => {
  it.each([
    [
      "nothing set on the server: Desktop values move up",
      UNSET,
      true,
      "plan",
      undefined,
      { start_in_plan_mode: true, auto_publish_cloud_runs: true },
      null,
      true,
    ],
    [
      "'Last used' is not offered to the server",
      UNSET,
      false,
      "last_used",
      undefined,
      { auto_publish_cloud_runs: false },
      null,
      false,
    ],
    [
      "values chosen on web win on the first sync",
      { start_in_plan_mode: false, auto_publish_cloud_runs: false },
      true,
      "plan",
      undefined,
      {},
      false,
      false,
    ],
    [
      "a Desktop change since the last sync moves up",
      { start_in_plan_mode: true, auto_publish_cloud_runs: true },
      false,
      "plan",
      { autoPublishCloudRuns: true, planModeOffered: true },
      { auto_publish_cloud_runs: false },
      null,
      false,
    ],
    [
      "a web change since the last sync comes down",
      { start_in_plan_mode: true, auto_publish_cloud_runs: false },
      true,
      "plan",
      { autoPublishCloudRuns: true, planModeOffered: true },
      {},
      false,
      false,
    ],
    [
      "in step: nothing to do",
      { start_in_plan_mode: null, auto_publish_cloud_runs: true },
      true,
      "plan",
      { autoPublishCloudRuns: true, planModeOffered: true },
      {},
      null,
      true,
    ],
  ] as const)(
    "%s",
    (_case, server, local, mode, synced, upload, pull, agreed) => {
      expect(
        nextTaskDefaultsSync({
          server,
          localAutoPublishCloudRuns: local,
          localInitialTaskMode: mode,
          synced,
        }),
      ).toEqual({
        upload,
        pullAutoPublishCloudRuns: pull,
        synced: { autoPublishCloudRuns: agreed, planModeOffered: true },
      });
    },
  );
});
