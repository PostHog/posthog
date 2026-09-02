import type {
  SandboxCustomImage,
  SandboxEnvironment,
} from "@posthog/shared/domain-types";

export type CloudTarget =
  | { kind: "default" }
  | { kind: "environment"; id: string }
  | { kind: "image"; id: string };

export const DEFAULT_CLOUD_TARGET: CloudTarget = { kind: "default" };

export interface CloudTargetOption {
  key: string;
  target: CloudTarget;
  name: string;
  description: string;
}

export function cloudTargetKey(target: CloudTarget): string {
  return target.kind === "default" ? "default" : `${target.kind}:${target.id}`;
}

export function cloudTargetFromKey(key: string | null): CloudTarget | null {
  if (!key) return null;
  if (key === "default") return DEFAULT_CLOUD_TARGET;
  const [kind, id] = key.split(":");
  if (!id) return null;
  if (kind === "environment") return { kind: "environment", id };
  if (kind === "image") return { kind: "image", id };
  return null;
}

export function cloudTargetIds(target: CloudTarget): {
  sandboxEnvironmentId?: string;
  customImageId?: string;
} {
  if (target.kind === "environment") return { sandboxEnvironmentId: target.id };
  if (target.kind === "image") return { customImageId: target.id };
  return {};
}

function environmentDescription(environment: SandboxEnvironment): string {
  if (environment.network_access_level === "full") return "Full network access";
  if (environment.network_access_level === "trusted") {
    return "Trusted sources only";
  }
  const count = environment.allowed_domains.length;
  return `${count} allowed domain${count === 1 ? "" : "s"}`;
}

export function buildCloudTargetOptions({
  environments,
  images,
  imagesEnabled,
}: {
  environments: readonly SandboxEnvironment[];
  images: readonly SandboxCustomImage[];
  imagesEnabled: boolean;
}): CloudTargetOption[] {
  const attachedImageIds = new Set(
    environments.flatMap((environment) =>
      environment.custom_image_id ? [environment.custom_image_id] : [],
    ),
  );
  const standaloneImages = imagesEnabled
    ? images.filter(
        (image) => image.status === "ready" && !attachedImageIds.has(image.id),
      )
    : [];

  return [
    {
      key: "default",
      target: DEFAULT_CLOUD_TARGET,
      name: "Default",
      description: "Full network access",
    },
    ...environments.map((environment) => ({
      key: cloudTargetKey({ kind: "environment", id: environment.id }),
      target: { kind: "environment" as const, id: environment.id },
      name: environment.name,
      description: environmentDescription(environment),
    })),
    ...standaloneImages.map((image) => ({
      key: cloudTargetKey({ kind: "image", id: image.id }),
      target: { kind: "image" as const, id: image.id },
      name: image.name,
      description: `v${image.version}, full network access`,
    })),
  ];
}

export function resolveCloudTarget(
  favorite: CloudTarget | null,
  options: readonly CloudTargetOption[],
): CloudTarget {
  if (!favorite) return DEFAULT_CLOUD_TARGET;
  return options.some((option) => option.key === cloudTargetKey(favorite))
    ? favorite
    : DEFAULT_CLOUD_TARGET;
}

export function moveFavoriteFirst(
  options: readonly CloudTargetOption[],
  favoriteKey: string | null,
): CloudTargetOption[] {
  const favorite = options.find((option) => option.key === favoriteKey);
  if (!favorite) return [...options];
  return [favorite, ...options.filter((option) => option !== favorite)];
}
