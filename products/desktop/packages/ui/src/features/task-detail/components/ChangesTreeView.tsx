import {
  buildChangeTree,
  type ChangeTreeNode,
  compactChangeTree,
  orderedTreeDirs,
  orderedTreeFiles,
} from "@posthog/core/git-interaction/changeTree";
import type { ChangedFile } from "@posthog/shared/domain-types";
import { TreeDirectoryRow } from "@posthog/ui/primitives/TreeDirectoryRow";
import { useCallback, useMemo, useState } from "react";

interface ChangesTreeNodeProps {
  node: ChangeTreeNode;
  depth: number;
  collapsedDirs: Set<string>;
  onToggleDir: (path: string) => void;
  renderFile: (file: ChangedFile, depth: number) => React.ReactNode;
}

function ChangesTreeNode({
  node,
  depth,
  collapsedDirs,
  onToggleDir,
  renderFile,
}: ChangesTreeNodeProps) {
  const isCollapsed = collapsedDirs.has(node.path);
  const sortedDirs = useMemo(() => orderedTreeDirs(node), [node]);
  const sortedFiles = useMemo(() => orderedTreeFiles(node), [node]);

  return (
    <>
      {node.path && (
        <TreeDirectoryRow
          name={node.name}
          depth={depth}
          isExpanded={!isCollapsed}
          onToggle={() => onToggleDir(node.path)}
        />
      )}
      {!isCollapsed && (
        <>
          {sortedDirs.map((child) => (
            <ChangesTreeNode
              key={child.path}
              node={child}
              depth={node.path ? depth + 1 : depth}
              collapsedDirs={collapsedDirs}
              onToggleDir={onToggleDir}
              renderFile={renderFile}
            />
          ))}
          {sortedFiles.map((file) =>
            renderFile(file, node.path ? depth + 1 : depth),
          )}
        </>
      )}
    </>
  );
}

interface ChangesTreeViewProps {
  files: ChangedFile[];
  renderFile: (file: ChangedFile, depth: number) => React.ReactNode;
}

export function ChangesTreeView({ files, renderFile }: ChangesTreeViewProps) {
  const tree = useMemo(
    () => compactChangeTree(buildChangeTree(files)),
    [files],
  );
  const [collapsedDirs, setCollapsedDirs] = useState<Set<string>>(new Set());

  const handleToggleDir = useCallback((path: string) => {
    setCollapsedDirs((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  }, []);

  return (
    <ChangesTreeNode
      node={tree}
      depth={0}
      collapsedDirs={collapsedDirs}
      onToggleDir={handleToggleDir}
      renderFile={renderFile}
    />
  );
}
