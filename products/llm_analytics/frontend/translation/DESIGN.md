# LLM Analytics Translation Feature - Design Document

## Overview

This document outlines the design options and decisions for adding a translation feature to LLM Analytics trace views. The feature allows users to translate AI conversation messages into English (or other target languages).

## Problem Statement

Users of LLM Analytics often work with traces containing conversations in multiple languages. Currently, there's no way to translate these messages within the trace view, forcing users to copy text and use external translation tools.

## Goals

1. Allow users to translate individual messages in trace conversations
2. Provide a simple, non-intrusive UI that follows existing patterns
3. Support multiple translation providers for flexibility
4. Keep the MVP simple enough for a hackathon implementation

## Non-Goals (for MVP)

- Auto-detection and auto-translation of non-English content
- Batch translation of entire traces
- Text selection-based translation
- Translation memory/caching (can be added later)

---

## UI Approach Options

### Option A: Per-Message Translate Button (Recommended)

Add a translate icon button to each message header, alongside existing buttons (copy, markdown toggle, XML toggle).

```text
┌─────────────────────────────────────────────────────────────┐
│ user                          [👁] [M] [</>] [🌐] [📋]      │
├─────────────────────────────────────────────────────────────┤
│ Hola, ¿cómo puedo ayudarte hoy?                            │
└─────────────────────────────────────────────────────────────┘
```

**Pros:**

- Follows existing UI patterns (copy, markdown, XML toggles)
- Simple to implement - similar to `ExplainCSPViolationButton`
- Per-message granularity gives users control
- Non-intrusive - button only appears when needed

**Cons:**

- Can't translate arbitrary text selections
- Need to click each message separately

### Option B: Text Selection Popup

User selects text, a floating "Translate" button appears near the selection.

**Pros:**

- Maximum flexibility - translate any text
- Natural interaction pattern (similar to Google Docs)

**Cons:**

- More complex to implement (text selection detection, positioning)
- New UI pattern for PostHog
- May conflict with native text selection

### Option C: Translate Entire Event

Single button in event header to translate all messages at once.

**Pros:**

- One click translates everything
- Simple UI

**Cons:**

- All-or-nothing approach
- May be expensive for long conversations
- User loses context of which parts were originally in which language

### Decision: Option A

Per-message translate button is the best balance of simplicity and utility for the hackathon MVP. It follows existing patterns and can be extended later.

---

## Translation API Options

### Option 1: OpenAI GPT-4o-mini (Recommended for MVP)

Use the existing OpenAI integration to translate text via the chat completions API.

**Pros:**

- Already integrated in PostHog backend
- High quality translations with context awareness
- Can handle nuanced language and technical terms
- No additional API keys needed

**Cons:**

- Slower than dedicated translation APIs (~1-2s vs ~100ms)
- More expensive per character than translation APIs
- Uses AI credits

**Cost:** ~$0.15 per 1M input tokens, ~$0.60 per 1M output tokens

**Implementation:**

```python
response = openai.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": "Translate the following text to English. Only return the translation, nothing else."},
        {"role": "user", "content": text_to_translate}
    ]
)
```

### Option 2: Google Cloud Translation API

**Pros:**

- Fast (~100ms response time)
- Accurate for common languages
- Cheap at scale

**Cons:**

- Requires new API key setup
- Additional dependency
- Less context-aware than LLM

**Cost:** $20 per 1M characters

### Option 3: DeepL API

**Pros:**

- Highest quality translations, especially for European languages
- Good at preserving tone and style

**Cons:**

- Requires separate API key
- More expensive than Google
- Limited free tier

**Cost:** $25 per 1M characters (Pro API)

### Option 4: LibreTranslate (Self-hosted)

**Pros:**

- Free and open source
- Can be self-hosted for privacy
- No API costs

**Cons:**

- Quality varies by language pair
- Requires infrastructure setup
- Not as accurate as commercial options

### Decision: OpenAI GPT-4o-mini for MVP

For the hackathon, OpenAI is the pragmatic choice because:

1. Already integrated - no new API setup
2. Good enough quality for translation
3. Can be swapped out later via abstraction layer

---

## Display Options

### Option A: Popover/Tooltip (Recommended)

Show translation in a floating popover near the original message.

```text
┌─────────────────────────────────────────────────────────────┐
│ Hola, ¿cómo puedo ayudarte hoy?                            │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ 🌐 Translation                                     [×] │ │
│ │ Hello, how can I help you today?                       │ │
│ │ Detected: Spanish → English                            │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

**Pros:**

- Original text remains visible for comparison
- Click outside to dismiss
- Follows `ExplainCSPViolationButton` pattern

**Cons:**

- Takes up screen space
- May overlap other content

### Option B: Inline Replacement

Replace message content with translation, with toggle to show original.

**Pros:**

- Clean, no overlapping UI
- Persistent display

**Cons:**

- Original text hidden by default
- Need state management for toggle

### Option C: Side-by-Side

Show original and translation in two columns.

**Pros:**

- Easy comparison
- Both visible at once

**Cons:**

- Takes significant horizontal space
- May not fit in current layout

### Decision: Option A (Popover)

Popover provides good UX while following existing patterns.

---

## Error States

1. **Translation failed**: Show error message in popover with retry button
2. **Content not translatable**: For JSON/images, show "This content type cannot be translated"
3. **Rate limited**: Show "Please wait before translating more content"
4. **Network error**: Show generic error with retry option

---

## Future Enhancements

After the MVP, consider:

1. **Translation caching**: Store translations to avoid repeated API calls
2. **Auto-detect non-English**: Show indicator when message is in non-English language
3. **Batch translation**: "Translate all" button for entire conversation
4. **Text selection translation**: Select arbitrary text to translate
5. **Language picker**: Allow translating to languages other than English
6. **Translation memory**: Learn from corrections for better future translations

---

## Security Considerations

1. **Data privacy**: Translation sends message content to external API
   - Document this in UI (tooltip/warning)
   - Consider offering self-hosted option for sensitive data

2. **Rate limiting**: Prevent abuse via excessive translation requests
   - Implement per-user rate limits

3. **Cost management**: Translation has per-request cost
   - Consider adding org-level translation limits
   - Show cost indicator if using paid API

---

## Analytics Events

Track usage for feature evaluation:

```typescript
posthog.capture('llm_analytics_translation_requested', {
    source_language_detected: 'es',
    target_language: 'en',
    message_length: 150,
    translation_provider: 'openai'
})

posthog.capture('llm_analytics_translation_completed', {
    duration_ms: 1200,
    success: true
})
```

---

## References

- [ExplainCSPViolationButton](../../lib/components/LLMButton/ExplainCSPViolationButton.tsx) - UI pattern reference
- [LLMMessageDisplay](./ConversationDisplay/ConversationMessagesDisplay.tsx) - Integration point
- [OpenAI Translation Guide](https://platform.openai.com/docs/guides/text-generation)
