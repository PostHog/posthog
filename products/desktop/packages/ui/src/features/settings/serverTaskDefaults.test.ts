import { describe, expect, it } from "vitest";
import { nextTaskDefaultsSync } from "./serverTaskDefaults";
import type { DefaultInitialTaskMode } from "./settingsStore";

const UNSET = { start_in_plan_mode: null, auto_publish_cloud_runs: null };
const OFF = { start_in_plan_mode: false, auto_publish_cloud_runs: false };
const ON = { start_in_plan_mode: true, auto_publish_cloud_runs: true };

interface Case {
  server: {
    start_in_plan_mode: boolean | null;
    auto_publish_cloud_runs: boolean | null;
  };
  autoPublish: boolean;
  mode: DefaultInitialTaskMode;
  synced:
    | { autoPublishCloudRuns: boolean; startInPlanMode?: boolean }
    | undefined;
  upload: Record<string, boolean>;
  pullAutoPublish: boolean | null;
  pullMode: DefaultInitialTaskMode | null;
  agreed: { autoPublishCloudRuns: boolean; startInPlanMode: boolean };
}

describe("serverTaskDefaults", () => {
  it.each<[string, Case]>([
    [
      "first sync, nothing set on the server: pull requests move up, plan mode reads as off and Desktop follows",
      {
        server: UNSET,
        autoPublish: true,
        mode: "plan",
        synced: undefined,
        upload: { auto_publish_cloud_runs: true },
        pullAutoPublish: null,
        pullMode: "last_used",
        agreed: { autoPublishCloudRuns: true, startInPlanMode: false },
      },
    ],
    [
      "first sync, nothing set on the server, Desktop on Last used: nothing changes for plan mode",
      {
        server: UNSET,
        autoPublish: false,
        mode: "last_used",
        synced: undefined,
        upload: { auto_publish_cloud_runs: false },
        pullAutoPublish: null,
        pullMode: null,
        agreed: { autoPublishCloudRuns: false, startInPlanMode: false },
      },
    ],
    [
      "first sync, values off on web: web wins",
      {
        server: OFF,
        autoPublish: true,
        mode: "plan",
        synced: undefined,
        upload: {},
        pullAutoPublish: false,
        pullMode: "last_used",
        agreed: { autoPublishCloudRuns: false, startInPlanMode: false },
      },
    ],
    [
      "first sync, values on on web: web wins",
      {
        server: ON,
        autoPublish: false,
        mode: "last_used",
        synced: undefined,
        upload: {},
        pullAutoPublish: true,
        pullMode: "plan",
        agreed: { autoPublishCloudRuns: true, startInPlanMode: true },
      },
    ],
    [
      "state saved before plan mode synced: the plan mode sync starts as a first sync",
      {
        server: OFF,
        autoPublish: false,
        mode: "plan",
        synced: { autoPublishCloudRuns: false },
        upload: {},
        pullAutoPublish: null,
        pullMode: "last_used",
        agreed: { autoPublishCloudRuns: false, startInPlanMode: false },
      },
    ],
    [
      "a Desktop change since the last sync moves up",
      {
        server: ON,
        autoPublish: false,
        mode: "last_used",
        synced: { autoPublishCloudRuns: true, startInPlanMode: true },
        upload: { auto_publish_cloud_runs: false, start_in_plan_mode: false },
        pullAutoPublish: null,
        pullMode: null,
        agreed: { autoPublishCloudRuns: false, startInPlanMode: false },
      },
    ],
    [
      "a Desktop change to Plan moves up over an unset server value",
      {
        server: UNSET,
        autoPublish: true,
        mode: "plan",
        synced: { autoPublishCloudRuns: true, startInPlanMode: false },
        upload: { auto_publish_cloud_runs: true, start_in_plan_mode: true },
        pullAutoPublish: null,
        pullMode: null,
        agreed: { autoPublishCloudRuns: true, startInPlanMode: true },
      },
    ],
    [
      "a web change since the last sync comes down",
      {
        server: OFF,
        autoPublish: true,
        mode: "plan",
        synced: { autoPublishCloudRuns: true, startInPlanMode: true },
        upload: {},
        pullAutoPublish: false,
        pullMode: "last_used",
        agreed: { autoPublishCloudRuns: false, startInPlanMode: false },
      },
    ],
    [
      "both sides changed: Desktop wins",
      {
        server: OFF,
        autoPublish: false,
        mode: "last_used",
        synced: { autoPublishCloudRuns: true, startInPlanMode: true },
        upload: { auto_publish_cloud_runs: false, start_in_plan_mode: false },
        pullAutoPublish: null,
        pullMode: null,
        agreed: { autoPublishCloudRuns: false, startInPlanMode: false },
      },
    ],
    [
      "in step: nothing to do",
      {
        server: ON,
        autoPublish: true,
        mode: "plan",
        synced: { autoPublishCloudRuns: true, startInPlanMode: true },
        upload: {},
        pullAutoPublish: null,
        pullMode: null,
        agreed: { autoPublishCloudRuns: true, startInPlanMode: true },
      },
    ],
  ])("%s", (_case, c) => {
    expect(
      nextTaskDefaultsSync({
        server: c.server,
        localAutoPublishCloudRuns: c.autoPublish,
        localInitialTaskMode: c.mode,
        synced: c.synced,
      }),
    ).toEqual({
      upload: c.upload,
      pullAutoPublishCloudRuns: c.pullAutoPublish,
      pullInitialTaskMode: c.pullMode,
      synced: c.agreed,
    });
  });
});
