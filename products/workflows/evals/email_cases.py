from pathlib import Path


def email_case(name: str, brief: str, cta_urls: list[str], count: int = 1) -> dict:
    return {
        "name": name,
        "prompt": brief,
        "expected": {
            "email_structure": {"count": count, "cta_urls": cta_urls},
            "email_prose": {"brief": brief},
        },
    }


CASES = [
    email_case(
        "welcome_sequence",
        "Write a three-email welcome sequence for CloudShelf, a fictional file-sharing app. "
        "New signups have not uploaded a file. The first email invites them to upload a file today. "
        "Two days later, show how a shared link lets a colleague open a file without an account. "
        "Five days later, suggest creating a project folder to keep related files together. "
        "Each email should ask for only its own next action. Use these destinations in order: "
        "https://example.com/upload, https://example.com/share, https://example.com/folders. "
        "No discounts, trial deadlines, or invented features.",
        ["https://example.com/upload", "https://example.com/share", "https://example.com/folders"],
        count=3,
    ),
    email_case(
        "finish_onboarding",
        "Write one onboarding reminder for PlotPad, a fictional shared garden-planning app. "
        "The recipient created a garden but has not added a bed. Adding the first bed lets them "
        "place crops and see how much space remains. They signed up two days ago. "
        "Be helpful without guilt or urgency. Ask them to add their first bed at "
        "https://example.org/garden/beds. Do not ask them to invite friends or upgrade.",
        ["https://example.org/garden/beds"],
    ),
    email_case(
        "reengagement",
        "Write one re-engagement email for LoopNotes, a fictional rehearsal-notes app for bands. "
        "The recipient has not opened it for 30 days. Their notes remain saved and they can "
        "pick up the last rehearsal plan. Ask them to open that plan at "
        "https://example.com/rehearsals/latest. No new features have launched. "
        "Do not claim that bandmates miss them, threaten deletion, or offer a discount.",
        ["https://example.com/rehearsals/latest"],
    ),
]


def drafting_instructions() -> str:
    skills = Path(__file__).parents[1] / "skills"
    paths = [
        skills / "building-workflows/SKILL.md",
        skills / "designing-email-templates/SKILL.md",
        skills / "designing-email-templates/references/unlayer-design-json.md",
        skills / "designing-email-templates/references/design-guidelines.md",
    ]
    return (
        "The user is creating a new PostHog workflow. Draft only its emails, without executing tools "
        "or enabling a workflow. Apply the email-authoring guidance below. Return a JSON object with "
        "an emails array in sequence order. Each email has subject, text (a complete plain-text "
        "rendering including its CTA URL), and design or html. No markdown fences or commentary.\n\n"
        + "\n\n".join(path.read_text() for path in paths)
    )
