import type { SketchpadFragment } from "@posthog/shared";
import { useCallback, useState } from "react";

interface ApprovedCode {
  sketchpadId: string;
  fragments: Pick<SketchpadFragment, "id" | "code">[];
}

export interface SketchpadCodeTrust {
  stopped: boolean;
  start: () => void;
  stop: () => void;
}

export function useSketchpadCodeTrust(
  sketchpadId: string,
  fragments: readonly SketchpadFragment[],
): SketchpadCodeTrust {
  const [approved, setApproved] = useState<ApprovedCode | null>(null);
  const [manuallyStopped, setManuallyStopped] = useState(false);
  const hasCode = fragments.length > 0;
  const approvedCurrentCode =
    approved?.sketchpadId === sketchpadId &&
    sameCode(approved.fragments, fragments);

  const start = useCallback((): void => {
    setApproved({
      sketchpadId,
      fragments: fragments.map(({ id, code }) => ({ id, code })),
    });
    setManuallyStopped(false);
  }, [fragments, sketchpadId]);
  const stop = useCallback((): void => setManuallyStopped(true), []);

  return {
    stopped: manuallyStopped || (hasCode && !approvedCurrentCode),
    start,
    stop,
  };
}

function sameCode(
  approved: readonly Pick<SketchpadFragment, "id" | "code">[],
  current: readonly SketchpadFragment[],
): boolean {
  if (approved.length !== current.length) return false;
  const byId = new Map(
    approved.map((fragment) => [fragment.id, fragment.code]),
  );
  return current.every((fragment) => byId.get(fragment.id) === fragment.code);
}
