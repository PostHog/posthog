interface SidebarCountBadgeProps {
  count: number;
  title: string;
}

export function SidebarCountBadge({ count, title }: SidebarCountBadgeProps) {
  if (count <= 0) return null;
  return (
    <span
      className="ml-2 inline-flex h-2 w-2 shrink-0 rounded-full bg-(--red-9)"
      title={title}
    />
  );
}
