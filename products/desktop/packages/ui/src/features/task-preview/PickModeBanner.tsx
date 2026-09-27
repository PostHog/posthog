import { Button } from "@posthog/quill";

export function PickModeBanner({ onCancel }: { onCancel: () => void }) {
  return (
    <div className="-translate-x-1/2 absolute top-3 left-1/2 z-20 flex items-center gap-3 rounded-full border border-primary bg-background px-3 py-1.5 shadow-md">
      <span className="whitespace-nowrap text-foreground text-xs">
        Click an element to comment on it
      </span>
      <Button
        variant="link-muted"
        size="xs"
        data-attr="task-preview-pick-cancel"
        onClick={onCancel}
      >
        Cancel
      </Button>
    </div>
  );
}
