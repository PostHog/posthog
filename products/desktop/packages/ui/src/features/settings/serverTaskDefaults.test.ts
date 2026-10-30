import { describe, expect, it } from "vitest";
import { nextTaskDefaultsSync } from "./serverTaskDefaults";

const UNSET = { start_in_plan_mode: null, auto_publish_cloud_runs: null };

describe("serverTaskDefaults", () => {
  it.each([
    [
      "nothing set on the server: only pull requests move up, plan mode stays off",
      UNSET,
      true,
      undefined,
      { auto_publish_cloud_runs: true },
      null,
      true,
    ],
    [
      "values chosen on web win on the first sync",
      { start_in_plan_mode: false, auto_publish_cloud_runs: false },
      true,
      undefined,
      {},
      false,
      false,
    ],
    [
      "a Desktop change since the last sync moves up",
      { start_in_plan_mode: true, auto_publish_cloud_runs: true },
      false,
      { autoPublishCloudRuns: true },
      { auto_publish_cloud_runs: false },
      null,
      false,
    ],
    [
      "a web change since the last sync comes down",
      { start_in_plan_mode: true, auto_publish_cloud_runs: false },
      true,
      { autoPublishCloudRuns: true },
      {},
      false,
      false,
    ],
    [
      "in step: nothing to do",
      { start_in_plan_mode: null, auto_publish_cloud_runs: true },
      true,
      { autoPublishCloudRuns: true },
      {},
      null,
      true,
    ],
  ] as const)("%s", (_case, server, local, synced, upload, pull, agreed) => {
    expect(
      nextTaskDefaultsSync({
        server,
        localAutoPublishCloudRuns: local,
        synced,
      }),
    ).toEqual({
      upload,
      pullAutoPublishCloudRuns: pull,
      synced: { autoPublishCloudRuns: agreed },
    });
  });
});
