type DividerSize = "1" | "2" | "3";

interface DividerProps {
  size?: DividerSize;
}

const SIZE_TO_MARGIN: Record<DividerSize, string> = {
  "1": "my-2",
  "2": "my-3",
  "3": "my-4",
};

export function Divider({ size = "2" }: DividerProps) {
  return (
    <hr
      className={`border-0 border-t border-t-(--gray-6) ${SIZE_TO_MARGIN[size]}`}
    />
  );
}
