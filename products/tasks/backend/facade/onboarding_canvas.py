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
# validates this source against the contract. Animations are plain CSS because
# the canvas builder cannot currently bundle framer-motion.
TEACHING_CANVAS_CODE = """\
import { useState } from "react";
import { Button, Heading, Text } from "@posthog/quill";
import { ArrowLeft, ArrowRight, Bot, BookOpen, Check, Hash, LayoutDashboard } from "lucide-react";

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

const TOUR_STYLES = `
@keyframes tour-fade-up { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
@keyframes tour-slide-in { from { opacity: 0; transform: translateX(14px); } to { opacity: 1; transform: none; } }
.tour-fade-up { animation: tour-fade-up 0.35s cubic-bezier(0.2, 0.8, 0.2, 1) backwards; }
.tour-slide-in { animation: tour-slide-in 0.25s cubic-bezier(0.2, 0.8, 0.2, 1) backwards; }
@media (prefers-reduced-motion: reduce) {
  .tour-fade-up, .tour-slide-in { animation: none; }
}
`;

function IconChip({ icon: Icon }) {
  return (
    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border bg-muted">
      <Icon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
    </div>
  );
}

function StopProgress({ current }) {
  return (
    <div className="flex items-center gap-1.5" aria-hidden="true">
      {TOPICS.map((topic, index) => (
        <div
          key={topic.id}
          className={"h-1 w-6 rounded-full " + (index === current ? "bg-foreground" : "bg-border")}
        />
      ))}
    </div>
  );
}

function HomeView({ onOpen, seen, allSeen }) {
  return (
    <div className="tour-fade-up flex flex-col gap-6">
      <div className="flex flex-col gap-1.5">
        <Heading size="2xl" render={<h1 />}>
          How PostHog Desktop works
        </Heading>
        <Text variant="muted">A quick tour in four stops. Pick one.</Text>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {TOPICS.map((topic, index) => (
          <div
            key={topic.id}
            className="tour-fade-up transition-transform duration-150 hover:-translate-y-0.5 motion-reduce:transition-none motion-reduce:hover:transform-none"
            style={{ animationDelay: 0.05 * index + 0.05 + "s" }}
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
                {seen[topic.id] ? (
                  <Check className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" aria-label="Seen" />
                ) : (
                  <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                )}
              </div>
            </Button>
          </div>
        ))}
      </div>
      <div className="border-t border-border pt-4">
        <Text size="sm" variant="muted">
          {allSeen
            ? "That's the whole tour. You can delete this canvas whenever you like, and ask the agent for a new one any time."
            : "This page is a canvas: a small app that lives in this space. Delete it whenever you like."}
        </Text>
      </div>
    </div>
  );
}

function DetailView({ topic, index, next, onBack, onNext }) {
  return (
    <div className="tour-slide-in flex flex-col gap-5">
      <div className="flex items-center justify-between">
        <Button variant="link-muted" size="sm" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          All topics
        </Button>
        <StopProgress current={index} />
      </div>
      <div className="flex flex-col gap-3">
        <Text size="xs" variant="muted" className="uppercase tracking-wider">
          Stop {index + 1} of {TOPICS.length}
        </Text>
        <div className="flex items-center gap-3">
          <IconChip icon={topic.icon} />
          <div className="flex flex-col">
            <Heading size="2xl" render={<h1 />}>
              {topic.title}
            </Heading>
            <Text size="sm" variant="muted">
              {topic.tagline}
            </Text>
          </div>
        </div>
      </div>
      <div className="flex flex-col gap-3">
        {topic.body.map((paragraph) => (
          <Text key={paragraph}>{paragraph}</Text>
        ))}
      </div>
      <div className="flex flex-col gap-2.5 rounded-lg border border-border bg-muted p-4">
        <Text size="sm" weight="medium">
          Try asking
        </Text>
        <div className="flex flex-col items-start gap-2">
          {topic.prompts.map((prompt) => (
            <div key={prompt} className="rounded-lg border border-border bg-background px-3 py-2">
              <Text size="sm">“{prompt}”</Text>
            </div>
          ))}
        </div>
      </div>
      <div className="flex justify-end border-t border-border pt-4">
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
    </div>
  );
}

export default function StartHere() {
  const [topicId, setTopicId] = useState(null);
  const [seen, setSeen] = useState({});
  const open = (id) => {
    setSeen((prev) => ({ ...prev, [id]: true }));
    setTopicId(id);
  };
  const index = TOPICS.findIndex((topic) => topic.id === topicId);
  const topic = index === -1 ? null : TOPICS[index];
  const next = topic && index < TOPICS.length - 1 ? TOPICS[index + 1] : null;
  const allSeen = TOPICS.every((entry) => seen[entry.id]);
  return (
    <div className="h-screen overflow-y-auto bg-background">
      <style>{TOUR_STYLES}</style>
      <div className="mx-auto max-w-2xl px-6 py-12" key={topic ? topic.id : "home"}>
        {topic ? (
          <DetailView
            topic={topic}
            index={index}
            next={next}
            onBack={() => setTopicId(null)}
            onNext={() => next && open(next.id)}
          />
        ) : (
          <HomeView onOpen={open} seen={seen} allSeen={allSeen} />
        )}
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
