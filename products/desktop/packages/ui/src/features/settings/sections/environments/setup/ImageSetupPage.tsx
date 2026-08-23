import { Spinner } from "@posthog/quill";
import type { SandboxCustomImage } from "@posthog/shared/domain-types";
import { EnvironmentSetupFlow } from "@posthog/ui/features/settings/sections/environments/setup/EnvironmentSetupFlow";
import { useSandboxCustomImages } from "@posthog/ui/features/settings/sections/environments/useSandboxCustomImages";

interface ImageSetupPageProps {
  /** Preselected repository, e.g. the one a recommendation was about. */
  defaultRepository: string | null;
  onDone: (building: SandboxCustomImage | null) => void;
  /** True when a surrounding dialog already supplies the title and the way back. */
  embedded?: boolean;
}

/**
 * Builds a sandbox image and nothing else. The same steps an environment uses
 * for its base image, without creating an environment nobody asked for.
 */
export function ImageSetupPage({
  defaultRepository,
  onDone,
  embedded = false,
}: ImageSetupPageProps) {
  const { images, isLoading } = useSandboxCustomImages();

  if (isLoading) {
    return (
      <div className="flex h-40 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return (
    <EnvironmentSetupFlow
      scope="image"
      defaultRepository={defaultRepository}
      buildImage
      environments={[]}
      images={images}
      embedded={embedded}
      onDone={onDone}
    />
  );
}
