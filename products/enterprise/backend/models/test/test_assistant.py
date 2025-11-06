from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest

from django.utils import timezone

from products.enterprise.backend.models.assistant import CoreMemory


class TestCoreMemory(BaseTest):
    def setUp(self):
        super().setUp()
        self.core_memory = CoreMemory.objects.create(team=self.team)

    def test_status_changes(self):
        # Test pending status
        self.core_memory.change_status_to_pending()
        self.assertEqual(self.core_memory.scraping_status, CoreMemory.ScrapingStatus.PENDING)
        self.assertIsNotNone(self.core_memory.scraping_started_at)

        # Test skipped status
        self.core_memory.change_status_to_skipped()
        self.assertEqual(self.core_memory.scraping_status, CoreMemory.ScrapingStatus.SKIPPED)

    def test_scraping_status_properties(self):
        # Test pending status within time window
        self.core_memory.change_status_to_pending()
        self.assertTrue(self.core_memory.is_scraping_pending)

        # Test pending status outside time window
        self.core_memory.scraping_started_at = timezone.now() - timedelta(minutes=11)
        self.core_memory.save()
        self.assertFalse(self.core_memory.is_scraping_pending)

        # Test finished status
        self.core_memory.scraping_status = CoreMemory.ScrapingStatus.COMPLETED
        self.core_memory.save()
        self.assertTrue(self.core_memory.is_scraping_finished)

        self.core_memory.scraping_status = CoreMemory.ScrapingStatus.SKIPPED
        self.core_memory.save()
        self.assertTrue(self.core_memory.is_scraping_finished)

    @freeze_time("2023-01-01 12:00:00")
    def test_is_scraping_pending_timing(self):
        # Set initial pending status
        self.core_memory.change_status_to_pending()
        initial_time = timezone.now()

        # Test 3 minutes after (should be true)
        with freeze_time(initial_time + timedelta(minutes=3)):
            self.assertTrue(self.core_memory.is_scraping_pending)

        # Test exactly 5 minutes after (should be false)
        with freeze_time(initial_time + timedelta(minutes=10)):
            self.assertFalse(self.core_memory.is_scraping_pending)

        # Test 6 minutes after (should be false)
        with freeze_time(initial_time + timedelta(minutes=11)):
            self.assertFalse(self.core_memory.is_scraping_pending)

    def test_core_memory_operations(self):
        # Test setting core memory
        test_text = "Test memory content"
        self.core_memory.set_core_memory(test_text)
        self.assertEqual(self.core_memory.text, test_text)
        self.assertEqual(self.core_memory.initial_text, "")
        self.assertEqual(self.core_memory.scraping_status, CoreMemory.ScrapingStatus.COMPLETED)

        # Test appending core memory
        append_text = "Additional content"
        self.core_memory.append_core_memory(append_text)
        self.assertEqual(self.core_memory.text, f"{test_text}\n{append_text}")

        # Test replacing core memory
        original = "content"
        new = "memory"
        self.core_memory.replace_core_memory(original, new)
        self.assertIn(new, self.core_memory.text)
        self.assertNotIn(original, self.core_memory.text)

        # Test replacing non-existent content
        with self.assertRaises(ValueError):
            self.core_memory.replace_core_memory("nonexistent", "new")

    def test_formatted_text(self):
        # Test formatted text with short content
        short_text = "Short text"
        self.core_memory.set_core_memory(short_text)
        self.assertEqual(self.core_memory.formatted_text, short_text)

        # Test formatted text with long content
        long_text = "x" * 6000
        self.core_memory.set_core_memory(long_text)
        self.assertEqual(len(self.core_memory.formatted_text), 5001)
        self.assertEqual(self.core_memory.formatted_text, long_text[:2500] + "…" + long_text[-2500:])
