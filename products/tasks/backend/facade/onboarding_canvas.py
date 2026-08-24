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
import { Text } from "@posthog/quill";
import { Bot, BookOpen, Hash, LayoutDashboard } from "lucide-react";

const SECTIONS = [
  {
    id: "spaces",
    icon: Hash,
    title: "Spaces",
    body:
      "Spaces organize work with your team. #general is shared with everyone in your workspace. " +
      "Each space has a feed of tasks and reports, plus its own canvases, like this one.",
  },
  {
    id: "agent",
    icon: Bot,
    title: "The agent",
    body:
      "Type what you want done in any space. The agent can query your product data, investigate " +
      "errors, watch for problems, and open pull requests in your repos. Each request becomes a " +
      "task you can follow and steer.",
  },
  {
    id: "context",
    icon: BookOpen,
    title: "Context",
    body:
      "Each space keeps shared context that the agent reads before it starts any task. What your " +
      "company does gets saved there, so you don't have to repeat yourself. Open a space's " +
      "context page to read or edit it.",
  },
  {
    id: "canvases",
    icon: LayoutDashboard,
    title: "Canvases",
    body:
      "Canvases are small apps that live in a space: dashboards, forms, tools, prototypes. They " +
      "can run live queries against your PostHog data. To make one, or to change this one, ask " +
      "the agent.",
  },
];

const PROMPTS = [
  "Build a canvas that charts signups by week.",
  "What are our top errors this week?",
  "Add PostHog to my repo and open a pull request.",
];

export default function StartHere() {
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto flex max-w-xl flex-col gap-5 p-6">
        <div className="flex flex-col gap-1">
          <Text size="lg" weight="semibold">
            How PostHog Desktop works
          </Text>
          <Text size="sm" variant="muted">
            This page is a canvas: a small app that lives in this space. The agent builds and
            changes canvases for you. This one is a quick tour.
          </Text>
        </div>
        <div className="flex flex-col gap-3">
          {SECTIONS.map((section) => {
            const Icon = section.icon;
            return (
              <div key={section.id} className="flex flex-col gap-1 rounded-md border p-3">
                <div className="flex items-center gap-2">
                  <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                  <Text weight="medium">{section.title}</Text>
                </div>
                <Text size="sm" variant="muted">
                  {section.body}
                </Text>
              </div>
            );
          })}
        </div>
        <div className="flex flex-col gap-1">
          <Text weight="medium">Things to try</Text>
          {PROMPTS.map((prompt) => (
            <Text key={prompt} size="sm" variant="muted">
              "{prompt}"
            </Text>
          ))}
        </div>
        <Text size="sm" variant="muted">
          Done with this page? You can delete it from the space whenever you like.
        </Text>
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
