import { PencilSimple } from "@phosphor-icons/react";
import { Badge, Button, Text } from "@posthog/quill";
import type {
  NetworkAccessLevel,
  SandboxEnvironment,
} from "@posthog/shared/domain-types";

const ACCESS_LABELS: Record<NetworkAccessLevel, string> = {
  full: "Full network",
  trusted: "Trusted sources",
  custom: "Custom allowlist",
};

interface EnvironmentListProps {
  environments: readonly SandboxEnvironment[];
  /** False when custom images are off, which hides the base image column. */
  imagesEnabled: boolean;
  onEdit: (environment: SandboxEnvironment) => void;
}

/** The environments a cloud session can run under, one row each. */
export function EnvironmentList({
  environments,
  imagesEnabled,
  onEdit,
}: EnvironmentListProps) {
  return (
    <div className="flex flex-col divide-y divide-border overflow-hidden rounded-(--radius-3) border border-border">
      {environments.map((environment) => (
        <div
          key={environment.id}
          className="flex items-center gap-3 px-3 py-2.5"
        >
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <Text className="truncate font-medium text-(--gray-12) text-[12.5px]">
              {environment.name}
            </Text>
            <div className="flex min-w-0 items-center gap-2">
              <Badge variant="default" className="text-[10.5px]">
                {ACCESS_LABELS[environment.network_access_level]}
              </Badge>
              {imagesEnabled && environment.custom_image_name && (
                <Text className="shrink-0 text-(--gray-10) text-[11px]">
                  on {environment.custom_image_name}
                </Text>
              )}
              {environment.repositories.length > 0 && (
                <Text className="min-w-0 truncate font-mono text-(--gray-10) text-[11px]">
                  {environment.repositories.join(", ")}
                </Text>
              )}
            </div>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="shrink-0"
            aria-label={`Edit ${environment.name}`}
            data-attr="environment-edit"
            onClick={() => onEdit(environment)}
          >
            <PencilSimple size={13} />
            Edit
          </Button>
        </div>
      ))}
    </div>
  );
}
