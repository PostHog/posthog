import { Folder as FolderIcon, Plus } from "@phosphor-icons/react";
import type { Environment } from "@posthog/workspace-client/environment";
import { Flex, IconButton, Text } from "@radix-ui/themes";
import type { RegisteredFolder } from "../../../folders/types";
import { EnvironmentRow } from "./EnvironmentRow";
import type { ProjectEnvironments } from "./LocalEnvironmentsSettings";

function extractOrgName(remoteUrl: string | null): string | null {
  if (!remoteUrl) return null;
  const sshMatch = remoteUrl.match(/:([^/]+)\//);
  if (sshMatch) return sshMatch[1];
  const httpsMatch = remoteUrl.match(/\.com\/([^/]+)\//);
  if (httpsMatch) return httpsMatch[1];
  return null;
}

interface ProjectEnvironmentCardProps {
  project: ProjectEnvironments;
  onCreate: (folder: RegisteredFolder) => void;
  onEdit: (folder: RegisteredFolder, environment: Environment) => void;
}

export function ProjectEnvironmentCard({
  project,
  onCreate,
  onEdit,
}: ProjectEnvironmentCardProps) {
  const { folder, environments } = project;
  const orgName = extractOrgName(folder.remoteUrl);

  return (
    <Flex
      direction="column"
      className="rounded-(--radius-2) border border-(--gray-5)"
    >
      <Flex align="center" justify="between" gap="2" px="3" py="2">
        <Flex align="center" gap="2" className="min-w-0 flex-1">
          <FolderIcon
            size={14}
            weight="regular"
            className="shrink-0 text-(--gray-9)"
          />
          <Flex align="center" gap="2" className="min-w-0">
            <Text truncate className="font-medium text-[13px]">
              {folder.name}
            </Text>
            {orgName && (
              <Text color="gray" className="text-[13px]">
                {orgName}
              </Text>
            )}
          </Flex>
        </Flex>
        <IconButton
          variant="outline"
          color="gray"
          size="1"
          onClick={() => onCreate(folder)}
          title="Create environment"
        >
          <Plus size={12} />
        </IconButton>
      </Flex>

      {environments.length > 0 && (
        <Flex
          direction="column"
          px="3"
          className="border-t border-t-(--gray-4)"
        >
          {environments.map((env, index) => (
            <EnvironmentRow
              key={env.id}
              environment={env}
              isLast={index === environments.length - 1}
              onClick={() => onEdit(folder, env)}
            />
          ))}
        </Flex>
      )}
    </Flex>
  );
}
