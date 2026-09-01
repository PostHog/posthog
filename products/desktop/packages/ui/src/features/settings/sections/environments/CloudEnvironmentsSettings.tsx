import { Plus } from "@phosphor-icons/react";
import type { SetupScope } from "@posthog/core/settings/environmentSetup";
import { Button, Text } from "@posthog/quill";
import type {
  SandboxCustomImage,
  SandboxEnvironment,
} from "@posthog/shared/domain-types";
import { CustomImageList } from "@posthog/ui/features/settings/sections/environments/CustomImageList";
import { EnvironmentList } from "@posthog/ui/features/settings/sections/environments/EnvironmentList";
import { ImageDetailPage } from "@posthog/ui/features/settings/sections/environments/ImageDetailPage";
import { EnvironmentEditPage } from "@posthog/ui/features/settings/sections/environments/setup/EnvironmentEditPage";
import { EnvironmentSetupFlow } from "@posthog/ui/features/settings/sections/environments/setup/EnvironmentSetupFlow";
import { useSandboxCustomImages } from "@posthog/ui/features/settings/sections/environments/useSandboxCustomImages";
import { useSandboxEnvironments } from "@posthog/ui/features/settings/sections/environments/useSandboxEnvironments";
import { useSettingsPageStore } from "@posthog/ui/features/settings/stores/settingsPageStore";
import { type ReactNode, useEffect, useState } from "react";

/**
 * Cloud environments and the images they start from. Each of the four things
 * you can be doing here (setting an environment up, editing one, building an
 * image, working on one) is its own page, so this stays a plain list.
 */
export function CloudEnvironmentsSettings() {
  const {
    environments,
    isLoading,
    isError: environmentsError,
    refetch: refetchEnvironments,
  } = useSandboxEnvironments();
  const {
    images,
    customImagesEnabled,
    isError: imagesError,
    refetch: refetchImages,
  } = useSandboxCustomImages();
  const consumeInitialAction = useSettingsPageStore(
    (s) => s.consumeInitialAction,
  );
  const setFormMode = useSettingsPageStore((s) => s.setFormMode);
  const [editingEnv, setEditingEnv] = useState<SandboxEnvironment | null>(null);
  const [openImage, setOpenImage] = useState<SandboxCustomImage | null>(null);
  const [setupFlow, setSetupFlow] = useState<SetupScope | null>(null);

  useEffect(() => {
    const action = consumeInitialAction();
    if (action === "create") {
      setSetupFlow("environment");
    }
  }, [consumeInitialAction]);

  const isPageOpen =
    editingEnv !== null || openImage !== null || setupFlow !== null;

  useEffect(() => {
    setFormMode(isPageOpen);
    return () => setFormMode(false);
  }, [isPageOpen, setFormMode]);

  // null while usage is unknown: the archive guard must fail closed instead
  // of reading a failed list as zero usages.
  const environmentsUsing = (imageId: string): readonly string[] | null => {
    if (environmentsError) return null;
    return environments
      .filter((environment) => environment.custom_image_id === imageId)
      .map((environment) => environment.name);
  };

  if (setupFlow) {
    return (
      <EnvironmentSetupFlow
        scope={setupFlow}
        defaultRepository={null}
        onDone={() => setSetupFlow(null)}
      />
    );
  }

  if (editingEnv) {
    return (
      <EnvironmentEditPage
        environment={editingEnv}
        onDone={() => setEditingEnv(null)}
        onBuildNewImage={() => {
          setEditingEnv(null);
          setSetupFlow("image");
        }}
      />
    );
  }

  if (openImage) {
    return (
      <ImageDetailPage
        image={openImage}
        usedBy={environmentsUsing(openImage.id)}
        onDone={() => setOpenImage(null)}
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <Section
        title="Environments"
        description="A profile a cloud session runs under: the repositories it works on, the hosts it may reach, and the image it starts from"
        action={
          <Button
            variant="outline"
            size="sm"
            data-attr="environment-new"
            onClick={() => setSetupFlow("environment")}
          >
            <Plus size={12} />
            New environment
          </Button>
        }
      >
        {isLoading ? (
          <Text className="text-(--gray-10) text-[12px]">
            Loading environments…
          </Text>
        ) : environmentsError ? (
          <ErrorNote
            message="The environments list could not be loaded."
            onRetry={() => void refetchEnvironments()}
          />
        ) : environments.length === 0 ? (
          <EmptyNote>
            Nothing here yet. Cloud sessions run with full network access until
            you set one up.
          </EmptyNote>
        ) : (
          <EnvironmentList
            environments={environments}
            imagesEnabled={customImagesEnabled}
            onEdit={setEditingEnv}
          />
        )}
      </Section>

      {customImagesEnabled && (
        <Section
          title="Images"
          description="A sandbox image built once with your tools and dependencies already installed; any environment can start from it"
          action={
            <Button
              variant="outline"
              size="sm"
              data-attr="custom-image-new"
              onClick={() => setSetupFlow("image")}
            >
              <Plus size={12} />
              New image
            </Button>
          }
        >
          {imagesError ? (
            <ErrorNote
              message="The images list could not be loaded."
              onRetry={() => void refetchImages()}
            />
          ) : images.length === 0 ? (
            <EmptyNote>
              No images yet. Sessions install what they need each run until you
              build one.
            </EmptyNote>
          ) : (
            <CustomImageList
              images={images}
              usedBy={(imageId) => {
                const used = environmentsUsing(imageId);
                return used === null ? null : used.length;
              }}
              onOpen={setOpenImage}
            />
          )}
        </Section>
      )}
    </div>
  );
}

/** A titled block: one line of explanation, its action, and its content. */
function Section({
  title,
  description,
  action,
  children,
}: {
  title: string;
  description: string;
  action: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex items-start gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <Text className="font-medium text-(--gray-12) text-[13px]">
            {title}
          </Text>
          <Text className="max-w-[68ch] text-(--gray-11) text-[11.5px] leading-snug">
            {description}
          </Text>
        </div>
        <span className="shrink-0">{action}</span>
      </div>
      {children}
    </div>
  );
}

function EmptyNote({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-(--radius-3) border border-border border-dashed px-3 py-3">
      <Text className="text-(--gray-11) text-[11.5px] leading-snug">
        {children}
      </Text>
    </div>
  );
}

/** A failed list load, named, with a way back. */
function ErrorNote({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-(--radius-3) border border-(--red-5) border-dashed px-3 py-3">
      <Text className="text-(--red-11) text-[11.5px] leading-snug">
        {message}
      </Text>
      <Button variant="outline" size="sm" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}
