/// <reference types="vite/client" />
import { File as PhosphorFileIcon } from "@phosphor-icons/react";
import { memo } from "react";
import { getIconForFile } from "vscode-icons-js";

const iconModules = import.meta.glob<string>("../assets/file-icons/*.svg", {
  eager: true,
  query: "?url",
  import: "default",
});

const ICON_MAP: Record<string, string> = {};
for (const [path, url] of Object.entries(iconModules)) {
  const filename = path.split("/").pop();
  if (filename) {
    ICON_MAP[filename] = url;
  }
}

interface FileIconProps {
  filename: string;
  size?: number;
}

export const FileIcon = memo(function FileIcon({
  filename,
  size = 14,
}: FileIconProps) {
  const iconName = getIconForFile(filename);

  if (!iconName || !ICON_MAP[iconName]) {
    return (
      <PhosphorFileIcon
        size={size}
        weight="regular"
        color="var(--gray-10)"
        className="shrink-0"
      />
    );
  }

  return (
    <img
      src={ICON_MAP[iconName]}
      width={size}
      height={size}
      alt=""
      className="shrink-0"
    />
  );
});
