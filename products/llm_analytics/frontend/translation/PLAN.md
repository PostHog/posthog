# LLM Analytics Translation Feature - Implementation Plan

## Overview

This document outlines the phased implementation plan for the translation feature in LLM Analytics.

## MVP Scope

For the hackathon MVP, we're implementing:

- Per-message translate button in conversation view
- Popover display for translations
- OpenAI GPT-4o-mini as translation backend
- English as target language (hardcoded for now)

## Phase 1: Frontend Component

**Goal:** Create the translate button component and integrate into message headers.

### Tasks

1. **Create `TranslateMessageButton.tsx`**
   - Location: `products/llm_analytics/frontend/ConversationDisplay/`
   - Follow `ExplainCSPViolationButton` pattern
   - Props: `content: string`
   - States: `loading`, `isOpen`, `translation`, `error`

2. **Add to message header**
   - Modify `ConversationMessagesDisplay.tsx`
   - Insert button after XML toggle, before copy button
   - Only show for text content (not JSON/images)

3. **Handle edge cases**
   - Empty content
   - Very long content (truncate display?)
   - Non-string content types

### Estimated Effort: 2-3 hours

## Phase 2: Backend Endpoint

**Goal:** Create API endpoint that handles translation requests.

### Tasks

1. **Create translation endpoint**
   - Location: `posthog/api/llm_analytics/translate.py`
   - Method: POST
   - Path: `/api/projects/{project_id}/llm_analytics/translate`

2. **Request/Response schema**

   ```python
   # Request
   {
       "text": "Hola mundo",
       "target_language": "en"  # optional, defaults to "en"
   }

   # Response
   {
       "translation": "Hello world",
       "detected_language": "es",  # optional
       "provider": "openai"
   }
   ```

3. **Translation provider abstraction**

   ```python
   class TranslationProvider(ABC):
       @abstractmethod
       def translate(self, text: str, target_language: str) -> TranslationResult:
           pass

   class OpenAITranslationProvider(TranslationProvider):
       def translate(self, text: str, target_language: str) -> TranslationResult:
           # Implementation
   ```

4. **Error handling**
   - API errors
   - Rate limiting
   - Content validation

### Estimated Effort: 2-3 hours

## Phase 3: API Integration

**Goal:** Wire up frontend to backend.

### Tasks

1. **Add API method**
   - Location: `frontend/src/lib/api.ts`
   - Add `llmAnalytics.translate()` method

2. **Connect component to API**
   - Update `TranslateMessageButton` to call API
   - Handle loading and error states

3. **Add analytics events**
   - Track translation requests
   - Track success/failure rates

### Estimated Effort: 1-2 hours

## Phase 4: Polish & Testing

**Goal:** Ensure quality and handle edge cases.

### Tasks

1. **Loading states**
   - Spinner in popover
   - Disabled button while loading

2. **Error handling UI**
   - Error message display
   - Retry button

3. **Manual testing**
   - Test with various languages
   - Test with long content
   - Test error scenarios

4. **Code review prep**
   - Clean up code
   - Add comments where needed
   - Ensure TypeScript types are correct

### Estimated Effort: 1-2 hours

## Total Estimated Effort

| Phase | Time |
|-------|------|
| Phase 1: Frontend | 2-3 hours |
| Phase 2: Backend | 2-3 hours |
| Phase 3: Integration | 1-2 hours |
| Phase 4: Polish | 1-2 hours |
| **Total** | **6-10 hours** |

## Dependencies

- OpenAI API key configured in environment
- Access to LLM Analytics feature flag (if applicable)

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| OpenAI API unavailable | Feature broken | Add retry logic, graceful error handling |
| Translation quality poor | Bad UX | Consider alternative providers post-MVP |
| Rate limiting | Users blocked | Implement client-side rate limiting |
| High API costs | Budget issues | Monitor usage, add limits if needed |

## Success Metrics

1. Users can successfully translate messages
2. Translation appears within 3 seconds
3. Error rate < 5%
4. Feature used by >10% of LLM Analytics users (post-launch)

## Rollout Plan

1. **Development**: Implement on feature branch
2. **Review**: Code review and testing
3. **Staging**: Deploy to staging for QA
4. **Production**: Gradual rollout via feature flag (optional)

## Post-MVP Roadmap

After hackathon, consider:

1. Translation caching (reduce API calls)
2. Auto-detect non-English (show translate hint)
3. Batch translation (entire conversation)
4. Text selection translation
5. Target language picker
