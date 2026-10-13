import type {
  SandboxCustomImage,
  SandboxEnvironment,
} from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  buildCloudTargetOptions,
  type CloudTarget,
  cloudTargetFromKey,
  cloudTargetIds,
  cloudTargetKey,
  moveFavoriteFirst,
  resolveCloudTarget,
} from "./cloudTargets";

const env = (overrides: Partial<SandboxEnvironment>): SandboxEnvironment =>
  ({
    id: "env-1",
    name: "Internal APIs",
    network_access_level: "custom",
    allowed_domains: ["github.com"],
    custom_image_id: null,
    ...overrides,
  }) as SandboxEnvironment;

const image = (overrides: Partial<SandboxCustomImage>): SandboxCustomImage =>
  ({
    id: "image-1",
    name: "posthog stack",
    status: "ready",
    version: 279,
    ...overrides,
  }) as SandboxCustomImage;

describe("cloudTargets", () => {
  it("offers an image that no environment starts from", () => {
    const options = buildCloudTargetOptions({
      environments: [env({})],
      images: [image({})],
      imagesEnabled: true,
    });

    expect(options.map((option) => option.key)).toEqual([
      "default",
      "environment:env-1",
      "image:image-1",
    ]);
  });

  it.each([
    [
      "attached to an environment",
      {
        environments: [env({ custom_image_id: "image-1" })],
        images: [image({})],
        imagesEnabled: true,
      },
    ],
    [
      "not ready",
      {
        environments: [env({})],
        images: [image({ status: "building" })],
        imagesEnabled: true,
      },
    ],
    [
      "images are off",
      {
        environments: [env({})],
        images: [image({})],
        imagesEnabled: false,
      },
    ],
  ])("hides an image that is %s", (_case, input) => {
    const options = buildCloudTargetOptions(input);

    expect(options.some((option) => option.key === "image:image-1")).toBe(
      false,
    );
  });

  it.each([
    [{ kind: "default" }, {}],
    [{ kind: "environment", id: "env-1" }, { sandboxEnvironmentId: "env-1" }],
    [{ kind: "image", id: "image-1" }, { customImageId: "image-1" }],
  ] as [CloudTarget, ReturnType<typeof cloudTargetIds>][])(
    "sends %o as %o",
    (target, ids) => {
      expect(cloudTargetIds(target)).toEqual(ids);
      expect(cloudTargetFromKey(cloudTargetKey(target))).toEqual(target);
    },
  );

  it("puts the favorite first", () => {
    const options = buildCloudTargetOptions({
      environments: [env({})],
      images: [image({})],
      imagesEnabled: true,
    });

    expect(
      moveFavoriteFirst(options, "image:image-1").map((option) => option.key),
    ).toEqual(["image:image-1", "default", "environment:env-1"]);
  });

  it("falls back to the default when the favorite is gone", () => {
    const options = buildCloudTargetOptions({
      environments: [],
      images: [],
      imagesEnabled: true,
    });

    expect(
      resolveCloudTarget({ kind: "image", id: "image-1" }, options),
    ).toEqual({ kind: "default" });
  });
});
