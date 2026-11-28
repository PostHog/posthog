"""Find the element a click step targets, the way a person looking at the page would.

One script runs in the page and returns a verdict. The script receives the step's selector, text
and href as its argument, never as source text, and its verdict is parsed as untrusted data,
because both come from outside PostHog.
"""

from __future__ import annotations

from enum import StrEnum

from posthog.dataclasses import frozen

from ..facade.contracts import ElementClickStep
from ..facade.enums import JourneyStepFailureReason
from .run_browser import BrowserPage

SELECTOR_PREVIEW_LENGTH = 120
URL_PREVIEW_LENGTH = 300

# Returns the first element that a person could click, or the reason no element qualifies.
#
# The checks follow what a person sees, not what the DOM holds. `scrollIntoView` and Playwright's
# visibility check both count an element as visible when a container with hidden overflow cuts it
# off, so this script scrolls only containers a person can scroll, then intersects the element's box
# with every ancestor that clips it. That intersection is what catches a nav item pushed out of a
# fixed-width menu.
CLASSIFY_ELEMENT_JS = r"""
(args) => {
    const normalize = (value) => (value || "").replace(/\s+/g, " ").trim();
    const wantedText = args.text === null ? null : normalize(args.text);
    let all;
    try {
        all = Array.from(document.querySelectorAll(args.selector));
    } catch (e) {
        return { status: "invalid_selector", matches: 0 };
    }
    const matches = all.filter((el) => {
        if (wantedText !== null && normalize(el.innerText || el.textContent) !== wantedText) {
            return false;
        }
        if (args.href !== null && el.getAttribute("href") !== args.href && el.href !== args.href) {
            return false;
        }
        return true;
    });
    if (matches.length === 0) {
        return { status: "not_found", matches: 0 };
    }

    const notRenderedReason = (el) => {
        if (el.getClientRects().length === 0) {
            return "display";
        }
        if (getComputedStyle(el).visibility !== "visible") {
            return "visibility";
        }
        for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
            if (parseFloat(getComputedStyle(node).opacity) === 0) {
                return "opacity";
            }
        }
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) {
            return "size";
        }
        return null;
    };

    const scrollable = (value) => value === "auto" || value === "scroll" || value === "overlay";
    const scrollLikeAPerson = (el) => {
        for (let node = el.parentElement; node && node !== document.body && node !== document.documentElement; node = node.parentElement) {
            const style = getComputedStyle(node);
            const box = node.getBoundingClientRect();
            const rect = el.getBoundingClientRect();
            if (scrollable(style.overflowY) && node.scrollHeight > node.clientHeight) {
                node.scrollTop += rect.top + rect.height / 2 - (box.top + node.clientTop + node.clientHeight / 2);
            }
            if (scrollable(style.overflowX) && node.scrollWidth > node.clientWidth) {
                node.scrollLeft += rect.left + rect.width / 2 - (box.left + node.clientLeft + node.clientWidth / 2);
            }
        }
        const rect = el.getBoundingClientRect();
        window.scrollBy(
            rect.left + rect.width / 2 - window.innerWidth / 2,
            rect.top + rect.height / 2 - window.innerHeight / 2,
        );
    };

    const intersect = (a, b) => {
        const left = Math.max(a.left, b.left);
        const top = Math.max(a.top, b.top);
        const right = Math.min(a.right, b.right);
        const bottom = Math.min(a.bottom, b.bottom);
        return { left, top, right, bottom, empty: right <= left || bottom <= top };
    };

    // An ancestor clips an element only when it lies on the element's containing block chain. An
    // absolutely positioned element escapes overflow on static ancestors, and a fixed one escapes
    // everything except an ancestor that creates a containing block for it.
    const formsFixedContainingBlock = (style) =>
        style.transform !== "none" ||
        style.filter !== "none" ||
        style.perspective !== "none" ||
        /paint|layout|strict|content/.test(style.contain || "");
    const clippedRect = (el) => {
        const r = el.getBoundingClientRect();
        let rect = { left: r.left, top: r.top, right: r.right, bottom: r.bottom, empty: false };
        let position = getComputedStyle(el).position;
        for (let node = el.parentElement; node && node !== document.body && node !== document.documentElement; node = node.parentElement) {
            const style = getComputedStyle(node);
            const containsElement =
                position === "fixed"
                    ? formsFixedContainingBlock(style)
                    : position === "absolute"
                      ? style.position !== "static" || formsFixedContainingBlock(style)
                      : true;
            if (!containsElement) {
                continue;
            }
            const paintContained = /paint|strict|content/.test(style.contain || "");
            const clipsX = paintContained || style.overflowX !== "visible";
            const clipsY = paintContained || style.overflowY !== "visible";
            if (clipsX || clipsY) {
                const box = node.getBoundingClientRect();
                const left = box.left + node.clientLeft;
                const top = box.top + node.clientTop;
                rect = intersect(rect, {
                    left: clipsX ? left : -Infinity,
                    right: clipsX ? left + node.clientWidth : Infinity,
                    top: clipsY ? top : -Infinity,
                    bottom: clipsY ? top + node.clientHeight : Infinity,
                });
                if (rect.empty) {
                    return rect;
                }
            }
            position = style.position;
        }
        return rect;
    };

    const describe = (el) => {
        let label = el.tagName.toLowerCase();
        if (el.id) {
            label += "#" + el.id;
        }
        const classes = Array.from(el.classList).slice(0, 2);
        if (classes.length) {
            label += "." + classes.join(".");
        }
        return label.slice(0, 80);
    };

    let firstFailure = null;
    for (let i = 0; i < matches.length; i++) {
        const el = matches[i];
        const reason = notRenderedReason(el);
        if (reason !== null) {
            firstFailure = firstFailure || { status: "not_rendered", detail: reason };
            continue;
        }
        scrollLikeAPerson(el);
        const visible = clippedRect(el);
        if (visible.empty) {
            firstFailure = firstFailure || { status: "clipped" };
            continue;
        }
        const onScreen = intersect(visible, { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight });
        if (onScreen.empty) {
            return { status: "outside_viewport", matches: matches.length, index: i };
        }
        const x = (onScreen.left + onScreen.right) / 2;
        const y = (onScreen.top + onScreen.bottom) / 2;
        const hit = document.elementFromPoint(x, y);
        const reachable = hit !== null && (hit === el || el.contains(hit) || (hit.shadowRoot !== null && hit.shadowRoot.contains(el)));
        if (!reachable) {
            return { status: "obscured", matches: matches.length, index: i, obscured_by: hit ? describe(hit) : null };
        }
        return { status: "ok", matches: matches.length, index: i, x, y };
    }
    return { ...firstFailure, matches: matches.length };
}
"""

_NOT_RENDERED_MESSAGES = {
    "display": "The element is in the page but isn't displayed.",
    "visibility": "The element is in the page but hidden with CSS visibility.",
    "opacity": "The element is in the page but fully transparent.",
    "size": "The element is in the page but has no width or height.",
}


class ElementStatus(StrEnum):
    OK = "ok"
    INVALID_SELECTOR = "invalid_selector"
    NOT_FOUND = "not_found"
    NOT_RENDERED = "not_rendered"
    CLIPPED = "clipped"
    OUTSIDE_VIEWPORT = "outside_viewport"
    OBSCURED = "obscured"


@frozen
class ElementVerdict:
    status: ElementStatus
    # How many elements match the selector, text and href, visible or not.
    matches: int
    # Where to click, in viewport pixels. Set only when `status` is `ok`.
    x: float | None = None
    y: float | None = None
    # Which check a `not_rendered` element failed.
    detail: str | None = None
    # A short description of the element that covers an `obscured` one.
    obscured_by: str | None = None

    @property
    def is_final(self) -> bool:
        """Whether waiting longer can't change the verdict."""
        # A selector that doesn't parse won't start parsing, so it isn't worth waiting for.
        return self.status in (ElementStatus.OK, ElementStatus.INVALID_SELECTOR)


@frozen
class StepFailure:
    reason: JourneyStepFailureReason
    message: str


def find_clickable(page: BrowserPage, step: ElementClickStep) -> ElementVerdict:
    result = page.evaluate(CLASSIFY_ELEMENT_JS, {"selector": step.selector, "text": step.text, "href": step.href})
    return parse_verdict(result)


def parse_verdict(result: object) -> ElementVerdict:
    """Read the script's answer, treating anything unexpected as no element found."""
    if not isinstance(result, dict):
        return ElementVerdict(status=ElementStatus.NOT_FOUND, matches=0)
    status = next((s for s in ElementStatus if s.value == result.get("status")), ElementStatus.NOT_FOUND)
    matches, x, y = result.get("matches"), _number(result.get("x")), _number(result.get("y"))
    if status == ElementStatus.OK and (x is None or y is None):
        status = ElementStatus.NOT_FOUND
    detail, obscured_by = result.get("detail"), result.get("obscured_by")
    return ElementVerdict(
        status=status,
        matches=matches if isinstance(matches, int) else 0,
        x=x,
        y=y,
        detail=detail if isinstance(detail, str) else None,
        obscured_by=obscured_by if isinstance(obscured_by, str) and obscured_by else None,
    )


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def preview(value: str, length: int) -> str:
    return value if len(value) <= length else value[: length - 1] + "…"


def _not_found(step: ElementClickStep) -> StepFailure:
    described = f'"{preview(step.selector, SELECTOR_PREVIEW_LENGTH)}"'
    if step.text is not None:
        described += f' with the text "{preview(step.text, SELECTOR_PREVIEW_LENGTH)}"'
    if step.href is not None:
        described += f' linking to "{preview(step.href, URL_PREVIEW_LENGTH)}"'
    return StepFailure(
        reason=JourneyStepFailureReason.ELEMENT_NOT_FOUND,
        message=f"No element on the page matches {described}.",
    )


def element_failure(step: ElementClickStep, verdict: ElementVerdict) -> StepFailure | None:
    """Why the step can't click, or None when the verdict found an element to click."""
    match verdict.status:
        case ElementStatus.OK:
            return None
        case ElementStatus.INVALID_SELECTOR:
            return StepFailure(
                reason=JourneyStepFailureReason.ELEMENT_NOT_FOUND,
                message=f'The selector "{preview(step.selector, SELECTOR_PREVIEW_LENGTH)}" isn\'t valid CSS.',
            )
        case ElementStatus.NOT_RENDERED:
            return StepFailure(
                reason=JourneyStepFailureReason.ELEMENT_NOT_VISIBLE,
                message=_NOT_RENDERED_MESSAGES.get(verdict.detail or "", _NOT_RENDERED_MESSAGES["display"]),
            )
        case ElementStatus.CLIPPED:
            return StepFailure(
                reason=JourneyStepFailureReason.ELEMENT_NOT_VISIBLE,
                message=(
                    "The element is in the page, but a container that hides its overflow cuts it off, "
                    "so no part of it is visible."
                ),
            )
        case ElementStatus.OUTSIDE_VIEWPORT:
            return StepFailure(
                reason=JourneyStepFailureReason.ELEMENT_OUTSIDE_VIEWPORT_UNREACHABLE,
                message="The element is outside the visible area, and the page can't be scrolled to it.",
            )
        case ElementStatus.OBSCURED:
            by = f" ({preview(verdict.obscured_by, 80)})" if verdict.obscured_by else ""
            return StepFailure(
                reason=JourneyStepFailureReason.ELEMENT_OBSCURED,
                message=f"Another element{by} covers the element, so a click would land on it instead.",
            )
    return _not_found(step)
