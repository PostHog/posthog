import { Spinner } from "@posthog/quill";
import { EnvironmentSetupFlow } from "@posthog/ui/features/settings/sections/environments/setup/EnvironmentSetupFlow";
import { useSandboxCustomImages } from "@posthog/ui/features/settings/sections/environments/useSandboxCustomImages";
import { useSandboxEnvironments } from "@posthog/ui/features/settings/sections/environments/useSandboxEnvironments";

interface EnvironmentSetupPageProps {
  /** Preselected repository, e.g. the one a recommendation was about. */
  defaultRepository: string | null;
  onDone: () => void;
}

/**
 * Waits for the environments and images before starting the flow: both decide
 * which choices the first steps can offer, and a plan seeded from an empty list
 * would offer the wrong ones.
 */
export function EnvironmentSetupPage({
  defaultRepository,
  onDone,
}: EnvironmentSetupPageProps) {
  const { environments, isLoading } = useSandboxEnvironments();
  const { images, isLoading: imagesLoading } = useSandboxCustomImages();

  if (isLoading || imagesLoading) {
    return (
      <div className="flex h-40 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return (
    <EnvironmentSetupFlow
      defaultRepository={defaultRepository}
      environments={environments}
      images={images}
      onDone={() => onDone()}
    />
  );
}
