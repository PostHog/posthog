"""Seed the teaching canvas the first onboarding session points people at.

The canvas is a short self-demonstrating tour: it teaches spaces, the agent,
space context, and canvases, and it is itself a canvas, so reading it is also
seeing one work. It is seeded once per team into #general, and the session's
followup carries its id so the agent can offer it with an ``open_canvas``
button.
"""

from uuid import UUID

from django.apps import apps
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.user import User

TEACHING_CANVAS_TEMPLATE_ID = "desktop-onboarding-teaching"
TEACHING_CANVAS_NAME = "Start here"

# Single-file source stored on Canvas.legacy_code: the desktop app transpiles it
# in the viewer with no build queued, so seeding is one row write. The imports
# must stay within the canvas platform allowlist; a canvas-product test
# validates this source against the contract.
TEACHING_CANVAS_CODE = """\
import { useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Button, Heading, Text } from "@posthog/quill";
import { ArrowLeft, ArrowRight, Bot, BookOpen, Hash, LayoutDashboard } from "lucide-react";

const TOPICS = [
  {
    id: "spaces",
    icon: Hash,
    title: "Spaces",
    tagline: "Where work happens with your team",
    body: [
      "A space is a shared feed of work. #general is open to everyone in your workspace, and your personal space is only yours.",
      "Each space collects the tasks you start there, the reports PostHog writes into it, and its own context and canvases.",
    ],
    prompts: ["What happened in this project this week?"],
  },
  {
    id: "agent",
    icon: Bot,
    title: "The agent",
    tagline: "Type what you want done",
    body: [
      "Every message you send in a space starts a task. The agent can query your product data, investigate errors, watch for problems, and open pull requests in your repos.",
      "You can follow along while it works, steer it mid-task, and pick up the thread later.",
    ],
    prompts: ["What are our top errors this week?", "Add PostHog to my repo and open a pull request."],
  },
  {
    id: "context",
    icon: BookOpen,
    title: "Context",
    tagline: "What the agent already knows",
    body: [
      "Each space keeps shared context that the agent reads before it starts any task. What your company does gets saved there, so you don't have to repeat yourself.",
      "Open a space's context page to read or edit it. Anything you correct there sticks for every future task.",
    ],
    prompts: ["Update this space's context with what my company does."],
  },
  {
    id: "canvases",
    icon: LayoutDashboard,
    title: "Canvases",
    tagline: "Small apps that live in a space",
    body: [
      "Canvases are apps the agent builds for you: dashboards, forms, tools, prototypes. They can run live queries against your PostHog data.",
      "This page is a canvas. To make a new one, or change this one, ask the agent.",
    ],
    prompts: ["Build a canvas that charts signups by week."],
  },
];

const spring = { type: "spring", stiffness: 380, damping: 32 };

function IconChip({ icon: Icon }) {
  return (
    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border bg-muted">
      <Icon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
    </div>
  );
}

function HomeView({ onOpen, reduced }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: reduced ? 0 : 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: reduced ? 0 : -8 }}
      transition={{ duration: 0.15 }}
      className="flex flex-col gap-6"
    >
      <div className="flex flex-col gap-1">
        <Heading size="xl" render={<h1 />}>
          How PostHog Desktop works
        </Heading>
        <Text variant="muted">A quick tour. Pick a topic to see how it works.</Text>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {TOPICS.map((topic, index) => (
          <motion.div
            key={topic.id}
            initial={{ opacity: 0, y: reduced ? 0 : 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ ...spring, delay: 0.04 * index }}
            whileHover={reduced ? undefined : { y: -2 }}
          >
            <Button
              variant="outline"
              className="h-auto w-full whitespace-normal p-4 text-left"
              onClick={() => onOpen(topic.id)}
            >
              <div className="flex w-full items-start gap-3">
                <IconChip icon={topic.icon} />
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <Text weight="medium">{topic.title}</Text>
                  <Text size="sm" variant="muted">
                    {topic.tagline}
                  </Text>
                </div>
                <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              </div>
            </Button>
          </motion.div>
        ))}
      </div>
      <Text size="sm" variant="muted">
        This page is a canvas: a small app that lives in this space. Done with the tour? You can
        delete it whenever you like.
      </Text>
    </motion.div>
  );
}

function DetailView({ topic, next, onBack, onNext, reduced }) {
  return (
    <motion.div
      initial={{ opacity: 0, x: reduced ? 0 : 16 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: reduced ? 0 : -16 }}
      transition={{ duration: 0.15 }}
      className="flex flex-col gap-5"
    >
      <div>
        <Button variant="link-muted" size="sm" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          All topics
        </Button>
      </div>
      <div className="flex items-center gap-3">
        <IconChip icon={topic.icon} />
        <div className="flex flex-col">
          <Heading size="xl" render={<h1 />}>
            {topic.title}
          </Heading>
          <Text size="sm" variant="muted">
            {topic.tagline}
          </Text>
        </div>
      </div>
      <div className="flex flex-col gap-3">
        {topic.body.map((paragraph) => (
          <Text key={paragraph}>{paragraph}</Text>
        ))}
      </div>
      <div className="flex flex-col gap-2 rounded-md border border-border bg-muted p-4">
        <Text size="sm" weight="medium">
          Try asking
        </Text>
        {topic.prompts.map((prompt) => (
          <Text key={prompt} size="sm" variant="muted">
            "{prompt}"
          </Text>
        ))}
      </div>
      <div className="flex justify-end">
        {next ? (
          <Button variant="outline" onClick={onNext}>
            Next: {next.title}
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Button>
        ) : (
          <Button variant="outline" onClick={onBack}>
            Back to all topics
          </Button>
        )}
      </div>
    </motion.div>
  );
}

export default function StartHere() {
  const [topicId, setTopicId] = useState(null);
  const reduced = !!useReducedMotion();
  const index = TOPICS.findIndex((topic) => topic.id === topicId);
  const topic = index === -1 ? null : TOPICS[index];
  const next = topic && index < TOPICS.length - 1 ? TOPICS[index + 1] : null;
  return (
    <div className="h-screen overflow-y-auto bg-background">
      <div className="mx-auto max-w-2xl px-6 py-10">
        <AnimatePresence mode="wait">
          {topic ? (
            <DetailView
              key={topic.id}
              topic={topic}
              next={next}
              reduced={reduced}
              onBack={() => setTopicId(null)}
              onNext={() => next && setTopicId(next.id)}
            />
          ) : (
            <HomeView key="home" onOpen={setTopicId} reduced={reduced} />
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
"""

TEACHING_CANVAS_DESCRIPTION = (
    "A short tour of PostHog Desktop for new users: spaces, the agent, space context, and canvases."
)

TEACHING_CANVAS_CONTEXT = (
    "This canvas is an onboarding tour for new PostHog Desktop users. It explains spaces, "
    "the agent, space context, and canvases. If you edit it, keep it short and plain."
)


@frozen
class TeachingCanvas:
    channel_id: UUID
    canvas_id: UUID


def ensure_teaching_canvas(team_id: int, channel_id: UUID, user: User) -> TeachingCanvas | None:
    """Get or seed the team's teaching canvas in its general space.

    The Canvas model belongs to the canvas product, which depends on tasks, so it is
    resolved through the app registry rather than imported (the same posture as
    ``loop_runs.context_canvas_is_visible``). Returns ``None`` when a previously
    seeded canvas was deleted: someone removed it on purpose, so a later joiner's
    onboarding does not put it back. Raises on failure; callers treat seeding as
    best-effort.
    """
    canvas_model = apps.get_model("canvas", "Canvas")
    existing = (
        canvas_model.objects.for_team(team_id)
        .filter(channel_id=channel_id, template_id=TEACHING_CANVAS_TEMPLATE_ID)
        .order_by("created_at")
        .values_list("id", "deleted")
        .first()
    )
    if existing is not None:
        canvas_id, deleted = existing
        return None if deleted else TeachingCanvas(channel_id=channel_id, canvas_id=canvas_id)
    created = canvas_model.objects.create(
        team_id=team_id,
        channel_id=channel_id,
        name=TEACHING_CANVAS_NAME,
        kind=canvas_model.KIND_FREEFORM,
        template_id=TEACHING_CANVAS_TEMPLATE_ID,
        description=TEACHING_CANVAS_DESCRIPTION,
        context=TEACHING_CANVAS_CONTEXT,
        legacy_code=TEACHING_CANVAS_CODE,
        pinned_at=timezone.now(),
        created_by=user,
    )
    return TeachingCanvas(channel_id=channel_id, canvas_id=created.id)
