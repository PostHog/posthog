import { CheckIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";

/**
 * "Publish changes" that says "Published" for a moment once it has worked. Without that the button
 * vanishes the instant the sharing query refetches, which reads as nothing having happened.
 */
export function PublishChangesButton({
  visible,
  isPending,
  onPublish,
  dataAttr,
}: {
  /** Whether there is anything to publish. */
  visible: boolean;
  isPending: boolean;
  /** Resolves to whether publishing worked. */
  onPublish: () => Promise<boolean>;
  dataAttr: string;
}) {
  const [published, setPublished] = useState(false);

  useEffect(() => {
    if (!published) return;
    const timer = window.setTimeout(() => setPublished(false), 2000);
    return () => window.clearTimeout(timer);
  }, [published]);

  return (
    <AnimatePresence mode="wait" initial={false}>
      {published ? (
        <motion.div
          key="published"
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          <Button variant="outline" data-attr={`${dataAttr}-done`}>
            <CheckIcon />
            Published
          </Button>
        </motion.div>
      ) : visible ? (
        <motion.div
          key="publish"
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          <Button
            variant="primary"
            loading={isPending}
            onClick={() => void onPublish().then((ok) => setPublished(ok))}
            data-attr={dataAttr}
          >
            Publish changes
          </Button>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
