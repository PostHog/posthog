import {
  CursorTextIcon,
  NotePencilIcon,
  PlusIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import type { SkillFileEntry } from "@posthog/shared";
import {
  TreeDirectoryRow,
  TreeFileRow,
} from "@posthog/ui/primitives/TreeDirectoryRow";
import { type ReactNode, useMemo, useState } from "react";

interface TreeDir {
  name: string;
  path: string;
  dirs: TreeDir[];
  files: { name: string; path: string }[];
}

function buildTree(files: SkillFileEntry[]): TreeDir {
  const root: TreeDir = { name: "", path: "", dirs: [], files: [] };
  for (const file of files) {
    const parts = file.path.split("/");
    let node = root;
    for (let i = 0; i < parts.length - 1; i++) {
      const dirPath = parts.slice(0, i + 1).join("/");
      let child = node.dirs.find((d) => d.path === dirPath);
      if (!child) {
        child = { name: parts[i] ?? "", path: dirPath, dirs: [], files: [] };
        node.dirs.push(child);
      }
      node = child;
    }
    node.files.push({ name: parts[parts.length - 1] ?? "", path: file.path });
  }
  return root;
}

function RowAction({
  label,
  icon,
  onClick,
}: {
  label: string;
  icon: ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className="rounded p-0.5 text-gray-9 transition-colors hover:bg-gray-4 hover:text-gray-12"
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
    >
      {icon}
    </button>
  );
}

interface SkillFileTreeProps {
  files: SkillFileEntry[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
  onEditFile?: (path: string) => void;
  onRenameFile?: (path: string) => void;
  onDeleteFile?: (path: string) => void;
  onAddFile?: () => void;
}

export function SkillFileTree({
  files,
  selectedPath,
  onSelect,
  onEditFile,
  onRenameFile,
  onDeleteFile,
  onAddFile,
}: SkillFileTreeProps) {
  const tree = useMemo(() => buildTree(files), [files]);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const toggleDir = (dirPath: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(dirPath)) {
        next.delete(dirPath);
      } else {
        next.add(dirPath);
      }
      return next;
    });
  };

  const renderDir = (dir: TreeDir, depth: number): ReactNode => (
    <div className="flex flex-col" key={dir.path || "__root"}>
      {dir.dirs.map((child) => {
        const isExpanded = !collapsed.has(child.path);
        return (
          <div className="flex flex-col" key={child.path}>
            <TreeDirectoryRow
              name={child.name}
              depth={depth}
              isExpanded={isExpanded}
              onToggle={() => toggleDir(child.path)}
            />
            {isExpanded && renderDir(child, depth + 1)}
          </div>
        );
      })}
      {dir.files.map((file) => {
        const isManifest = file.path === "SKILL.md";
        const actions = [
          onEditFile ? (
            <RowAction
              key="edit"
              label={isManifest ? "Edit the instructions" : "Edit this file"}
              icon={<NotePencilIcon size={12} />}
              onClick={() => onEditFile(file.path)}
            />
          ) : null,
          onRenameFile && !isManifest ? (
            <RowAction
              key="rename"
              label="Rename this file"
              icon={<CursorTextIcon size={12} />}
              onClick={() => onRenameFile(file.path)}
            />
          ) : null,
          onDeleteFile && !isManifest ? (
            <RowAction
              key="delete"
              label="Delete this file"
              icon={<TrashIcon size={12} />}
              onClick={() => onDeleteFile(file.path)}
            />
          ) : null,
        ].filter(Boolean);

        return (
          <TreeFileRow
            key={file.path}
            fileName={file.name}
            depth={depth}
            isActive={selectedPath === file.path}
            title={file.path}
            onClick={() => onSelect(file.path)}
            trailing={
              actions.length > 0 ? (
                <div className="flex shrink-0 items-center gap-0.5">
                  {actions}
                </div>
              ) : undefined
            }
          />
        );
      })}
    </div>
  );

  return (
    <div className="flex flex-col py-1">
      {renderDir(tree, 0)}
      {onAddFile ? (
        <button
          type="button"
          className="flex h-[22px] items-center gap-1.5 pl-[24px] text-[13px] text-gray-9 transition-colors hover:bg-gray-3 hover:text-gray-11"
          onClick={onAddFile}
        >
          <PlusIcon size={12} />
          Add file
        </button>
      ) : null}
    </div>
  );
}
