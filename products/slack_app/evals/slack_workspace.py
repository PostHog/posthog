"""An invented Slack workspace for the Slack app evals: people, apps, channels and threads.

Hedgebox, a file sharing company, runs its work in Slack. Every message here is written for
these evals, not taken from a real workspace. Each thread carries the labels its suites grade
against, so the daily summary and the work focus read the same conversations:

- ``newsworthy``: would a teammate who missed the day want to hear about the thread? This is
  the question the daily summary asks Jev about each root. ``None`` marks a thread where both
  answers are fair, which no suite grades.
- ``work``: what happened to the work the root asked the person for. ``open`` is still open,
  ``handed_off`` went to another AI agent without a tag, and ``done`` is finished. ``None``
  marks a thread with no work for PostHog in it.

The threads render through the production ``thread_text``, and app messages drop out the way
``read_thread`` drops them, so a suite reads each thread the way the models see it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from products.slack_app.backend.logic.onboarding.daily_summary import (
    ROOT_CHARS,
    RootRef,
    SummaryThread,
    tagged_users,
    thread_text,
)

Work = Literal["open", "handed_off", "done"]


@dataclass(frozen=True)
class Member:
    user_id: str
    name: str
    is_bot: bool = False


@dataclass(frozen=True)
class Message:
    user: str
    text: str
    # After DAY_START, so every thread lands on the same workday.
    minutes: int


@dataclass(frozen=True)
class Thread:
    key: str
    channel_id: str
    messages: tuple[Message, ...]
    newsworthy: bool | None
    work: Work | None = None

    @property
    def root(self) -> Message:
        return self.messages[0]

    @property
    def replies(self) -> tuple[Message, ...]:
        return self.messages[1:]


DAY_START = datetime(2027, 3, 9, 7, 0, tzinfo=UTC)

DANA = Member("U0DANA", "Dana")
ANA = Member("U0ANA", "Ana")
BEN = Member("U0BEN", "Ben")
CHLOE = Member("U0CHLOE", "Chloe")
RAJ = Member("U0RAJ", "Raj")
MEI = Member("U0MEI", "Mei")
POSTHOG = Member("U0POSTHOG", "PostHog", is_bot=True)
CLAUDE = Member("U0CLAUDE", "Claude", is_bot=True)
CURSOR = Member("U0CURSOR", "Cursor", is_bot=True)
MEMBERS = (DANA, ANA, BEN, CHLOE, RAJ, MEI, POSTHOG, CLAUDE, CURSOR)
BOT_IDS = frozenset(member.user_id for member in MEMBERS if member.is_bot)

# The person every digest in the evals is for.
PERSON = DANA

CHANNELS = {
    "C0INCIDENTS": "incidents",
    "C0GROWTH": "growth",
    "C0BACKEND": "eng-backend",
    "C0SUPPORT": "support-escalations",
    "C0LAUNCHES": "launches",
    "C0RANDOM": "random",
}


def _m(member: Member, text: str, minutes: int) -> Message:
    return Message(user=member.user_id, text=text, minutes=minutes)


def _tag(member: Member) -> str:
    return f"<@{member.user_id}>"


THREADS: tuple[Thread, ...] = (
    Thread(
        key="incident_upload_outage",
        channel_id="C0INCIDENTS",
        newsworthy=True,
        messages=(
            _m(BEN, "Uploads over 2 GB fail with a 502 since 09:40. Rolling back the storage proxy deploy now.", 160),
            _m(ANA, "Status page updated. Do we know how many uploads failed?", 166),
            _m(BEN, "Around one in twenty large uploads in the window. Small files were fine.", 171),
            _m(BEN, "Rollback done at 10:05, the error rate is back to normal.", 185),
            _m(ANA, "Thanks. Postmortem tomorrow at 10:00, I'll send the invite.", 190),
            _m(MEI, f"{_tag(DANA)} heads up, this dents today's upload numbers on the growth dashboard.", 200),
        ),
    ),
    Thread(
        key="decision_trial_length",
        channel_id="C0GROWTH",
        newsworthy=True,
        messages=(
            _m(
                DANA, "Decision needed by Thursday: do we cut the free trial from 30 to 14 days? Cohort data below.", 60
            ),
            _m(MEI, "The last two cohorts convert at about the same rate on day 14 and day 30.", 75),
            _m(ANA, "No objection from eng if it ships behind a flag.", 90),
            _m(CHLOE, "The trial banner copy says 30 days in three places, I can update it.", 95),
            _m(DANA, "Decided: 14 day trials behind the trial-length flag, for new signups from Monday.", 240),
        ),
    ),
    Thread(
        key="ask_onboarding_copy",
        channel_id="C0GROWTH",
        newsworthy=True,
        messages=(
            _m(
                CHLOE,
                f"{_tag(DANA)} two options for the onboarding checklist copy in Figma, which one do we ship? I need an answer by Friday.",
                110,
            ),
            _m(BEN, "Option B is shorter, which helps on mobile.", 130),
        ),
    ),
    Thread(
        key="open_trial_conversion_drop",
        channel_id="C0GROWTH",
        newsworthy=True,
        work="open",
        messages=(
            _m(
                MEI,
                f"{_tag(DANA)} trial to paid conversion dropped for the Tuesday cohort, can you find out why?",
                120,
            ),
            _m(BEN, "Nothing shipped on billing that day as far as I know.", 140),
            _m(CHLOE, "The paywall modal changed on Monday, could be related.", 150),
            _m(MEI, "Could be. I haven't split it by plan yet.", 155),
        ),
    ),
    Thread(
        key="handed_off_thumbnail_bug",
        channel_id="C0BACKEND",
        newsworthy=None,
        work="handed_off",
        messages=(
            _m(ANA, f"{_tag(DANA)} share link previews show the wrong thumbnail for PDFs.", 80),
            _m(DANA, "I asked Claude about this in a DM, it found the cache key and is writing the fix.", 100),
            _m(BEN, "Nice, ping me for the review.", 105),
        ),
    ),
    Thread(
        key="handed_off_rename_event",
        channel_id="C0BACKEND",
        newsworthy=None,
        work="handed_off",
        messages=(
            _m(ANA, f"{_tag(DANA)} the folder_renamed event fires twice on mobile web.", 125),
            _m(BEN, "The Cursor background agent picked this up, its draft PR is open.", 145),
            _m(ANA, "OK, I'll review it once CI is green.", 150),
        ),
    ),
    Thread(
        key="open_storage_usage_blocker",
        channel_id="C0SUPPORT",
        newsworthy=True,
        work="open",
        messages=(
            _m(
                RAJ,
                f"{_tag(DANA)} an enterprise workspace sees storage usage three times higher than their files add up to. They are holding the renewal on it.",
                170,
            ),
            _m(
                BEN,
                "Claude suggested we double count versioned files, but versions are excluded already, so it's not that.",
                195,
            ),
            _m(RAJ, "Still open, they want an answer this week.", 210),
        ),
    ),
    Thread(
        key="done_utm_params",
        channel_id="C0BACKEND",
        newsworthy=None,
        work="done",
        messages=(
            _m(ANA, f"{_tag(DANA)} the signup form drops the UTM parameters on Safari.", 30),
            _m(BEN, "Found it, the redirect strips the query string. Fixed in #482 and merged, it deploys at 3pm.", 70),
            _m(DANA, "Thanks!", 72),
        ),
    ),
    Thread(
        key="launch_shared_folders",
        channel_id="C0LAUNCHES",
        newsworthy=True,
        messages=(
            _m(ANA, "Shared folders v2 is live for every team. The changelog and docs are linked in the post.", 180),
            _m(CHLOE, "Congrats all!", 182),
            _m(RAJ, "Support macros are updated for it.", 200),
        ),
    ),
    Thread(
        key="blocker_release_migration",
        channel_id="C0BACKEND",
        newsworthy=True,
        messages=(
            _m(
                ANA,
                "Release 4.12 is blocked: the file_versions migration takes 40 minutes on staging. Ship without it, or split it?",
                50,
            ),
            _m(BEN, "Split it: add the column now and backfill in the background.", 65),
            _m(ANA, "Agreed, splitting it. The release moves to Thursday.", 85),
        ),
    ),
    Thread(
        key="status_heads_down",
        channel_id="C0BACKEND",
        newsworthy=False,
        messages=(
            _m(BEN, "Heads down on the storage migration today, slow to reply.", 10),
            _m(ANA, "👍", 12),
        ),
    ),
    Thread(
        key="chat_lunch",
        channel_id="C0RANDOM",
        newsworthy=False,
        messages=(
            _m(RAJ, "Tacos for lunch? Leaving at 12:15.", 280),
            _m(DANA, "In!", 282),
            _m(MEI, "Me too, save a seat.", 285),
        ),
    ),
    Thread(
        key="answered_2fa_reset",
        channel_id="C0SUPPORT",
        newsworthy=False,
        messages=(
            _m(RAJ, "How do I reset a user's 2FA from the admin panel?", 40),
            _m(BEN, "Admin, then Users, open the user, then Security, then Reset 2FA.", 45),
            _m(RAJ, "Thanks, done.", 48),
        ),
    ),
    Thread(
        key="chat_good_morning",
        channel_id="C0RANDOM",
        newsworthy=False,
        messages=(
            _m(CHLOE, "Good morning all ☀️", 5),
            _m(RAJ, "Morning!", 8),
        ),
    ),
    Thread(
        key="asked_posthog_app",
        channel_id="C0GROWTH",
        newsworthy=False,
        messages=(
            _m(MEI, f"{_tag(POSTHOG)} how many teams created a shared folder this week?", 220),
            _m(POSTHOG, "412 teams created at least one shared folder this week.", 222),
            _m(MEI, "Perfect, thanks.", 224),
        ),
    ),
    Thread(
        key="tagged_claude_directly",
        channel_id="C0BACKEND",
        newsworthy=None,
        work="handed_off",
        messages=(
            _m(ANA, f"{_tag(DANA)} the search index lags behind new uploads by about ten minutes.", 200),
            _m(DANA, f"{_tag(CLAUDE)} can you find out why the indexer falls behind?", 205),
            _m(CLAUDE, "On it. The indexer batches on a 10 minute timer, I'll propose a change.", 207),
        ),
    ),
)

BY_KEY = {thread.key: thread for thread in THREADS}


def _ts(minutes: int) -> str:
    return f"{(DAY_START + timedelta(minutes=minutes)).timestamp():.6f}"


def people_messages(thread: Thread) -> list[dict[str, str]]:
    """The messages ``read_thread`` would return: people only, with app posts dropped."""
    return [
        {"user": message.user, "text": message.text, "ts": _ts(message.minutes)}
        for message in thread.messages
        if message.user not in BOT_IDS
    ]


def permalink(thread: Thread) -> str:
    return f"https://hedgebox.example.com/archives/{thread.channel_id}/p{thread.key}"


def text_of(thread: Thread) -> str:
    return thread_text(people_messages(thread))


def root_ref(thread: Thread, score: float = 0.0) -> RootRef:
    """The index entry the sweep would build for the thread's root."""
    reply_users = tuple(dict.fromkeys(message.user for message in thread.replies))
    return RootRef(
        channel_id=thread.channel_id,
        ts=_ts(thread.root.minutes),
        author=thread.root.user,
        reply_count=len(thread.replies),
        latest_reply=float(_ts(thread.replies[-1].minutes)) if thread.replies else 0.0,
        reply_users=reply_users,
        mentions=tagged_users([thread.root.text]),
        score=score,
    )


def root_text(thread: Thread) -> str:
    return thread.root.text[:ROOT_CHARS]


def summary_thread(thread: Thread, person: Member = PERSON) -> SummaryThread:
    """The thread as ``summary_threads`` hands it to the writer."""
    messages = people_messages(thread)
    root = root_ref(thread)
    return SummaryThread(
        channel_id=thread.channel_id,
        ts=root.ts,
        text=thread_text(messages),
        involves_person=root.involves(person.user_id) or any(m["user"] == person.user_id for m in messages),
        permalink=permalink(thread),
        tagged=tagged_users(m["text"] for m in messages),
    )
