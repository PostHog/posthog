import { PencilSimple, Trash } from "@phosphor-icons/react";
import type { SkillFileEntry } from "@posthog/shared";
import {
  TreeDirectoryRow,
  TreeFileRow,
} from "@posthog/ui/primitives/TreeDirectoryRow";
import { Flex, Tooltip } from "@radix-ui/themes";
import { useMemo, useState } from "react";

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

interface SkillFileTreeProps {
  files: SkillFileEntry[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
  /** When set, file rows (except SKILL.md) get rename/delete actions. */
  onRenameFile?: (path: string) => void;
  onDeleteFile?: (path: string) => void;
}

export function SkillFileTree({
  files,
  selectedPath,
  onSelect,
  onRenameFile,
  onDeleteFile,
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

  const renderDir = (dir: TreeDir, depth: number): React.ReactNode => (
    <Flex direction="column" key={dir.path || "__root"}>
      {dir.dirs.map((child) => {
        const isExpanded = !collapsed.has(child.path);
        return (
          <Flex direction="column" key={child.path}>
            <TreeDirectoryRow
              name={child.name}
              depth={depth}
              isExpanded={isExpanded}
              onToggle={() => toggleDir(child.path)}
            />
            {isExpanded && renderDir(child, depth + 1)}
          </Flex>
        );
      })}
      {dir.files.map((file) => {
        const showActions =
          (onRenameFile || onDeleteFile) && file.path !== "SKILL.md";
        return (
          <TreeFileRow
            key={file.path}
            fileName={file.name}
            depth={depth}
            isActive={selectedPath === file.path}
            title={file.path}
            onClick={() => onSelect(file.path)}
            trailing={
              showActions ? (
                <Flex gap="1" className="shrink-0">
                  {onRenameFile && (
                    <Tooltip content="Rename file">
                      <button
                        type="button"
                        aria-label="Rename file"
                        className="rounded p-0.5 text-gray-9 hover:bg-gray-4 hover:text-gray-12"
                        onClick={(e) => {
                          e.stopPropagation();
                          onRenameFile(file.path);
                        }}
                      >
                        <PencilSimple size={12} />
                      </button>
                    </Tooltip>
                  )}
                  {onDeleteFile && (
                    <Tooltip content="Delete file">
                      <button
                        type="button"
                        aria-label="Delete file"
                        className="rounded p-0.5 text-gray-9 hover:bg-gray-4 hover:text-gray-12"
                        onClick={(e) => {
                          e.stopPropagation();
                          onDeleteFile(file.path);
                        }}
                      >
                        <Trash size={12} />
                      </button>
                    </Tooltip>
                  )}
                </Flex>
              ) : undefined
            }
          />
        );
      })}
    </Flex>
  );

  return renderDir(tree, 0);
}
