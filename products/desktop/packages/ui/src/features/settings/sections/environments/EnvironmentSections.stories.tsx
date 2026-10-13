import type {
  SandboxCustomImage,
  SandboxEnvironment,
} from "@posthog/shared/domain-types";
import { CustomImageList } from "@posthog/ui/features/settings/sections/environments/CustomImageList";
import { EnvironmentList } from "@posthog/ui/features/settings/sections/environments/EnvironmentList";
import type { Meta, StoryObj } from "@storybook/react";

const env = (overrides: Partial<SandboxEnvironment>): SandboxEnvironment =>
  ({
    id: "env-1",
    name: "Internal APIs",
    network_access_level: "custom",
    allowed_domains: ["github.com"],
    include_default_domains: true,
    repositories: ["posthog/posthog"],
    has_environment_variables: true,
    private: true,
    effective_domains: [],
    custom_image_id: "image-1",
    custom_image_name: "posthog toolchain",
    custom_image_status: "ready",
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  }) as SandboxEnvironment;

const image = (overrides: Partial<SandboxCustomImage>): SandboxCustomImage =>
  ({
    id: "image-1",
    name: "posthog toolchain",
    status: "ready",
    version: 248,
    repository: "posthog/posthog",
    private: false,
    ...overrides,
  }) as SandboxCustomImage;

/** Both lists together, which is how the settings page shows them. */
function EnvironmentSections({
  environments,
  images,
}: {
  environments: SandboxEnvironment[];
  images: SandboxCustomImage[];
}) {
  return (
    <div className="mx-auto flex max-w-[800px] flex-col gap-6 p-6">
      <EnvironmentList
        environments={environments}
        imagesEnabled
        onEdit={() => {}}
      />
      <CustomImageList
        images={images}
        usedBy={(id) =>
          environments.filter((e) => e.custom_image_id === id).length
        }
        onOpen={() => {}}
      />
    </div>
  );
}

const meta: Meta<typeof EnvironmentSections> = {
  title: "Environments/EnvironmentSections",
  component: EnvironmentSections,
  args: {
    environments: [
      env({}),
      env({
        id: "env-2",
        name: "hogdesk-impersonation",
        network_access_level: "full",
        repositories: [],
        custom_image_id: null,
        custom_image_name: null,
      }),
    ],
    images: [
      image({}),
      image({
        id: "image-2",
        name: "ai-gateway",
        repository: "posthog/ai-gateway",
        version: 12,
        status: "building",
      }),
      image({
        id: "image-3",
        name: "playwright runners",
        repository: null,
        version: 0,
        status: "build_failed",
      }),
    ],
  },
};

export default meta;

export const Populated: StoryObj<typeof EnvironmentSections> = {};
