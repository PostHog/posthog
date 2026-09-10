import { MagnifyingGlassIcon } from "@phosphor-icons/react";
import { Input } from "@posthog/quill";

/** A search field with the glass on the left. One offset, one height, one place. */
export function SearchInput({
  value,
  onValueChange,
  placeholder,
  ariaLabel,
  onBlur,
  className = "w-64",
}: {
  value: string;
  onValueChange: (value: string) => void;
  placeholder: string;
  /** Defaults to the placeholder, which reads the same to a screen reader. */
  ariaLabel?: string;
  onBlur?: () => void;
  /** The width of the field. */
  className?: string;
}) {
  return (
    <div className={`relative ${className}`}>
      <MagnifyingGlassIcon
        size={13}
        className="-translate-y-1/2 pointer-events-none absolute top-1/2 left-2.5 text-gray-10"
      />
      <Input
        type="search"
        value={value}
        onChange={(event) => onValueChange(event.target.value)}
        onBlur={onBlur}
        placeholder={placeholder}
        aria-label={ariaLabel ?? placeholder}
        className="h-8 pl-7"
      />
    </div>
  );
}
