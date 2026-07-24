import type { ChangedFile } from "@posthog/shared/domain-types";
import { TreeDirectoryRow } from "@posthog/ui/primitives/TreeDirectoryRow";
import { useCallback, useMemo, useState } from "react";

export interface TreeNode {
  name: string;
  path: string;
  children: Map<string, TreeNode>;
  files: ChangedFile[];
}

export function buildChangesTree(files: ChangedFile[]): TreeNode {
  const root: TreeNode = { name: "", path: "", children: new Map(), files: [] };
  for (const file of files) {
    const parts = file.path.split("/");
    let node = root;
    for (let i = 0; i < parts.length - 1; i++) {
      const part = parts[i];
      if (!node.children.has(part)) {
        node.children.set(part, {
          name: part,
          path: parts.slice(0, i + 1).join("/"),
          children: new Map(),
          files: [],
        });
      }
      const child = node.children.get(part);
      if (!child) break;
      node = child;
    }
    node.files.push(file);
  }
  return root;
}

/** Collapse single-child directory chains into one node (e.g. "src/utils") */
export function compactTree(node: TreeNode): TreeNode {
  const compacted = new Map<string, TreeNode>();
  for (const [key, child] of node.children) {
    let current = child;
    let label = current.name;
    while (current.children.size === 1 && current.files.length === 0) {
      const [, only] = [...current.children.entries()][0];
      label = `${label}/${only.name}`;
      current = only;
    }
    const result = compactTree(current);
    result.name = label;
    compacted.set(key, result);
  }
  return { ...node, children: compacted };
}

interface ChangesTreeNodeProps {
  node: TreeNode;
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
  const sortedDirs = useMemo(
    () =>
      [...node.children.values()].sort((a, b) => a.name.localeCompare(b.name)),
    [node.children],
  );
  const sortedFiles = useMemo(
    () =>
      [...node.files].sort((a, b) => {
        const aName = a.path.split("/").pop() || "";
        const bName = b.path.split("/").pop() || "";
        return aName.localeCompare(bName);
      }),
    [node.files],
  );

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
  const tree = useMemo(() => compactTree(buildChangesTree(files)), [files]);
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
