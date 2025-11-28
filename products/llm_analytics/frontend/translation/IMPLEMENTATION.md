# LLM Analytics Translation Feature - Implementation Guide

## Overview

This document provides detailed implementation guidance for the translation feature, including code examples and file locations.

## File Structure

```text
products/llm_analytics/
├── frontend/
│   ├── ConversationDisplay/
│   │   ├── ConversationMessagesDisplay.tsx  # Modify: add TranslateMessageButton
│   │   └── TranslateMessageButton.tsx       # NEW: Translation button component
│   └── translation/
│       ├── DESIGN.md
│       ├── PLAN.md
│       └── IMPLEMENTATION.md
│
posthog/
├── api/
│   └── llm_analytics/
│       ├── __init__.py                      # Modify: register new endpoint
│       └── translate.py                     # NEW: Translation API endpoint
│
frontend/src/lib/
└── api.ts                                   # Modify: add translate method
```

---

## Frontend Implementation

### TranslateMessageButton.tsx

```typescript
import { useState } from 'react'

import { IconLanguages } from '@posthog/icons'
import { Popover, Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

export interface TranslateMessageButtonProps {
    content: string
}

export const TranslateMessageButton = ({ content }: TranslateMessageButtonProps): JSX.Element | null => {
    const [loading, setLoading] = useState(false)
    const [isOpen, setIsOpen] = useState(false)
    const [translation, setTranslation] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)

    // Don't show button for empty content
    if (!content || content.trim().length === 0) {
        return null
    }

    const handleClick = async (): Promise<void> => {
        setIsOpen(true)
        setError(null)

        // If already translated, just show the cached translation
        if (translation) {
            return
        }

        setLoading(true)
        try {
            const response = await api.llmAnalytics.translate({ text: content })
            setTranslation(response.translation)
        } catch (e) {
            setError('Translation failed. Please try again.')
            console.error('Translation error:', e)
        } finally {
            setLoading(false)
        }
    }

    const handleRetry = async (): Promise<void> => {
        setTranslation(null)
        setError(null)
        setLoading(true)
        try {
            const response = await api.llmAnalytics.translate({ text: content })
            setTranslation(response.translation)
        } catch (e) {
            setError('Translation failed. Please try again.')
        } finally {
            setLoading(false)
        }
    }

    return (
        <Popover
            visible={isOpen}
            onClickOutside={() => setIsOpen(false)}
            placement="bottom"
            overlay={
                <div className="p-3 min-w-60 max-w-100">
                    <div className="flex items-center justify-between mb-2">
                        <span className="font-semibold text-sm">Translation</span>
                        <LemonButton
                            size="xsmall"
                            onClick={() => setIsOpen(false)}
                            icon={<span>×</span>}
                            noPadding
                        />
                    </div>
                    <div className="border-t pt-2">
                        {loading ? (
                            <div className="flex items-center justify-center py-4 gap-2">
                                <Spinner className="text-lg" />
                                <span className="text-muted">Translating...</span>
                            </div>
                        ) : error ? (
                            <div className="text-center py-2">
                                <p className="text-danger mb-2">{error}</p>
                                <LemonButton size="small" onClick={handleRetry}>
                                    Retry
                                </LemonButton>
                            </div>
                        ) : translation ? (
                            <div className="whitespace-pre-wrap text-sm">{translation}</div>
                        ) : null}
                    </div>
                </div>
            }
        >
            <LemonButton
                size="small"
                noPadding
                icon={<IconLanguages />}
                tooltip="Translate to English"
                onClick={handleClick}
            />
        </Popover>
    )
}
```

### Integration in ConversationMessagesDisplay.tsx

Find the message header section (around line 500-530) and add the translate button:

```typescript
// Import at top of file
import { TranslateMessageButton } from './TranslateMessageButton'

// In LLMMessageDisplay, after the XML toggle button (around line 525):
{isXmlCandidate && role !== 'tool' && role !== 'tools' && (
    <LemonButton
        size="small"
        noPadding
        icon={<IconCode />}
        tooltip="Toggle XML syntax highlighting"
        onClick={toggleXmlRendering}
        active={isRenderingXml}
    />
)}
{/* ADD THIS: Translate button */}
{typeof content === 'string' && content.trim().length > 0 && (
    <TranslateMessageButton content={content} />
)}
<CopyToClipboardInline
    iconSize="small"
    description="message content"
    explicitValue={typeof content === 'string' ? content : JSON.stringify(content)}
/>
```

---

## Backend Implementation

### translate.py

```python
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import Team


class TranslateRequestSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=10000)
    target_language = serializers.CharField(max_length=10, default="en")


class TranslateResponseSerializer(serializers.Serializer):
    translation = serializers.CharField()
    detected_language = serializers.CharField(required=False, allow_null=True)
    provider = serializers.CharField()


class TranslateView(TeamAndOrgViewSetMixin, APIView):
    """
    Translate text to a target language using LLM.
    """

    def post(self, request: Request, *args, **kwargs) -> Response:
        serializer = TranslateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        text = serializer.validated_data["text"]
        target_language = serializer.validated_data.get("target_language", "en")

        try:
            translation = self._translate_with_openai(text, target_language)
            response_data = {
                "translation": translation,
                "detected_language": None,  # Could be enhanced to detect source language
                "provider": "openai",
            }
            return Response(response_data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _translate_with_openai(self, text: str, target_language: str) -> str:
        """
        Translate text using OpenAI's GPT model.
        """
        import openai
        from django.conf import settings

        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)

        language_names = {
            "en": "English",
            "es": "Spanish",
            "fr": "French",
            "de": "German",
            "pt": "Portuguese",
            "zh": "Chinese",
            "ja": "Japanese",
            "ko": "Korean",
        }
        target_name = language_names.get(target_language, target_language)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": f"You are a translator. Translate the following text to {target_name}. "
                    "Only return the translation, nothing else. Preserve formatting.",
                },
                {"role": "user", "content": text},
            ],
            temperature=0.3,
            max_tokens=len(text) * 2,  # Allow room for expansion
        )

        return response.choices[0].message.content.strip()
```

### Register in __init__.py

```python
# In posthog/api/llm_analytics/__init__.py or urls.py

from posthog.api.llm_analytics.translate import TranslateView

urlpatterns = [
    # ... existing patterns
    path("translate", TranslateView.as_view(), name="llm_analytics_translate"),
]
```

---

## API Integration

### Update frontend/src/lib/api.ts

```typescript
// Find the existing API class and add:

llmAnalytics: {
    // ... existing methods

    translate(params: { text: string; targetLanguage?: string }): Promise<{
        translation: string
        detected_language?: string
        provider: string
    }> {
        return new ApiRequest()
            .projectsDetail(getCurrentTeamId())
            .addPathComponent('llm_analytics')
            .addPathComponent('translate')
            .create({ data: params })
    },
},
```

---

## Testing

### Manual Test Cases

1. __Basic translation__
   - Input: Spanish message "Hola, ¿cómo estás?"
   - Expected: English translation in popover

2. __Long content__
   - Input: Multi-paragraph message (500+ characters)
   - Expected: Full translation displayed

3. __Already English__
   - Input: English message
   - Expected: Same text returned (or "already in English" message)

4. __Special characters__
   - Input: Message with emojis, code blocks, special chars
   - Expected: Preserved in translation

5. __Error handling__
   - Simulate API failure
   - Expected: Error message with retry button

6. __Empty content__
   - Input: Empty or whitespace-only content
   - Expected: Button not shown

### Unit Test Example

```typescript
// TranslateMessageButton.test.tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { TranslateMessageButton } from './TranslateMessageButton'

jest.mock('lib/api', () => ({
    llmAnalytics: {
        translate: jest.fn(),
    },
}))

describe('TranslateMessageButton', () => {
    it('shows translation in popover on click', async () => {
        const api = require('lib/api')
        api.llmAnalytics.translate.mockResolvedValue({
            translation: 'Hello, how are you?',
        })

        render(<TranslateMessageButton content="Hola, ¿cómo estás?" />)

        fireEvent.click(screen.getByRole('button'))

        await waitFor(() => {
            expect(screen.getByText('Hello, how are you?')).toBeInTheDocument()
        })
    })

    it('handles error gracefully', async () => {
        const api = require('lib/api')
        api.llmAnalytics.translate.mockRejectedValue(new Error('API error'))

        render(<TranslateMessageButton content="Test" />)

        fireEvent.click(screen.getByRole('button'))

        await waitFor(() => {
            expect(screen.getByText(/Translation failed/)).toBeInTheDocument()
        })
    })

    it('does not render for empty content', () => {
        const { container } = render(<TranslateMessageButton content="" />)
        expect(container.firstChild).toBeNull()
    })
})
```

---

## Analytics Events

Add tracking to measure feature usage:

```typescript
// In TranslateMessageButton.tsx

import posthog from 'posthog-js'

const handleClick = async (): Promise<void> => {
    posthog.capture('llm_analytics_translate_clicked', {
        content_length: content.length,
    })

    // ... rest of handler

    try {
        const response = await api.llmAnalytics.translate({ text: content })
        posthog.capture('llm_analytics_translate_success', {
            content_length: content.length,
            translation_length: response.translation.length,
        })
        setTranslation(response.translation)
    } catch (e) {
        posthog.capture('llm_analytics_translate_error', {
            error: e instanceof Error ? e.message : 'Unknown error',
        })
        setError('Translation failed. Please try again.')
    }
}
```

---

## Environment Configuration

Ensure OpenAI API key is configured:

```bash
# .env or environment variables
OPENAI_API_KEY=sk-...
```

---

## Checklist

- [ ] Create `TranslateMessageButton.tsx` component
- [ ] Add translate button to message header in `ConversationMessagesDisplay.tsx`
- [ ] Create backend `translate.py` endpoint
- [ ] Register endpoint in URL routing
- [ ] Add `translate` method to frontend API
- [ ] Add analytics events
- [ ] Manual testing
- [ ] Code review
