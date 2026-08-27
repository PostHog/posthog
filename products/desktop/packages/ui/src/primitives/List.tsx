import type { ReactNode } from "react";

type ListSize = "1" | "1.5" | "2" | "3";

interface ListProps {
  children: ReactNode;
  size?: ListSize;
  as?: "ul" | "ol";
}

interface ListItemProps {
  children: ReactNode;
  size?: ListSize;
}

const sizeStyles: Record<ListSize, { className: string; itemSpacing: string }> =
  {
    "1": {
      className: "text-[13px]",
      itemSpacing: "mb-1",
    },
    "1.5": {
      className: "text-[13.5px]",
      itemSpacing: "mb-1",
    },
    "2": {
      className: "text-sm",
      itemSpacing: "mb-1",
    },
    "3": {
      className: "text-base",
      itemSpacing: "mb-2",
    },
  };

export function List({ children, as = "ul" }: ListProps) {
  const Component = as;

  return (
    <Component
      className={`my-2 list-outside pl-6 ${
        as === "ol" ? "list-decimal" : "list-disc"
      }`}
    >
      {children}
    </Component>
  );
}

export function ListItem({ children, size = "2" }: ListItemProps) {
  const styles = sizeStyles[size];

  return (
    <li
      className={`text-(--gray-12) ${styles.className} ${styles.itemSpacing}`}
    >
      {children}
    </li>
  );
}
