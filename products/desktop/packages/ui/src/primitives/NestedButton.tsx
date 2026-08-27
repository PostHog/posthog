import type React from "react";
import { forwardRef } from "react";

interface NestedButtonProps extends React.HTMLAttributes<HTMLSpanElement> {
  onActivate: () => void;
}

/**
 * A button nested inside another button. Rows like SidebarItem render as a real
 * `<button>`, and HTML forbids nesting a `<button>` inside one, so this is a
 * `<span role="button">` with full keyboard support instead. Click, double
 * click and Enter/Space stop propagation so the parent button does not also
 * fire. Forwards its ref and composes any injected handlers so it works as a
 * Radix `asChild` trigger (e.g. wrapped in a Tooltip).
 */
export const NestedButton = forwardRef<HTMLSpanElement, NestedButtonProps>(
  function NestedButton(
    { onActivate, onClick, onDoubleClick, onKeyDown, children, ...rest },
    ref,
  ) {
    return (
      // biome-ignore lint/a11y/useSemanticElements: nested clickable inside a parent <button> (e.g. SidebarItem)
      <span
        {...rest}
        ref={ref}
        role="button"
        tabIndex={0}
        onClick={(e) => {
          e.stopPropagation();
          onClick?.(e);
          onActivate();
        }}
        onDoubleClick={(e) => {
          e.stopPropagation();
          onDoubleClick?.(e);
        }}
        onKeyDown={(e) => {
          onKeyDown?.(e);
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            e.stopPropagation();
            onActivate();
          }
        }}
      >
        {children}
      </span>
    );
  },
);
