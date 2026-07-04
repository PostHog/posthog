import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.apps import apps

from posthog.rbac.user_access_control import UserAccessControl

from products.notebooks.backend import logic
from products.notebooks.backend.analytics import NotebookCreationSource
from products.notebooks.backend.facade import api, content
from products.notebooks.backend.models import Notebook, ResourceNotebook


def _create_account(team):
    # apps.get_model avoids a notebooks -> customer_analytics import edge (the FK is a string ref).
    Account = apps.get_model("customer_analytics", "Account")
    return Account.objects.unscoped().create(team=team, name="Acme")


class TestNotebooksFacade(BaseTest):
    def _doc(self, text: str = "hello") -> dict:
        return {"type": "doc", "content": [content.create_paragraph_with_text(text)]}

    def test_create_notebook_returns_contract(self):
        data = api.create_notebook(
            self.team.id,
            title="My notebook",
            content=self._doc(),
            created_by_id=self.user.id,
            last_modified_by_id=self.user.id,
        )
        self.assertEqual(data.title, "My notebook")
        self.assertEqual(data.visibility, Notebook.Visibility.DEFAULT)
        self.assertEqual(data.created_by_id, self.user.id)
        stored = Notebook.objects.get(id=data.id)
        self.assertEqual(stored.team_id, self.team.id)
        self.assertFalse(stored.deleted)

    def test_get_notebook_round_trips_fields(self):
        notebook = Notebook.objects.create(team=self.team, title="T", content=self._doc("body"), text_content="body")
        data = api.get_notebook(self.team.id, notebook.short_id)
        assert data is not None
        self.assertEqual(data.short_id, notebook.short_id)
        self.assertEqual(data.title, "T")
        self.assertEqual(data.text_content, "body")
        self.assertEqual(data.content, self._doc("body"))

    def test_get_notebook_excludes_deleted_by_default(self):
        notebook = Notebook.objects.create(team=self.team, title="gone", deleted=True)
        self.assertIsNone(api.get_notebook(self.team.id, notebook.short_id))
        self.assertIsNotNone(api.get_notebook(self.team.id, notebook.short_id, include_deleted=True))

    def test_notebook_exists_is_team_scoped(self):
        from posthog.models import Team

        notebook = Notebook.objects.create(team=self.team, title="t")
        other_team = Team.objects.create(organization=self.organization, name="other")
        self.assertTrue(api.notebook_exists(self.team.id, notebook.short_id))
        self.assertFalse(api.notebook_exists(other_team.id, notebook.short_id))

    def test_get_notebook_short_ids_for_creator(self):
        mine = Notebook.objects.create(team=self.team, title="mine", created_by=self.user)
        Notebook.objects.create(team=self.team, title="theirs")
        short_ids = api.get_notebook_short_ids_for_creator(self.team.project_id, self.user.id)
        self.assertEqual(short_ids, [mine.short_id])

    def test_activity_summary_orders_by_recency(self):
        Notebook.objects.create(team=self.team, title="old")
        newer = Notebook.objects.create(team=self.team, title="new")
        summary = api.get_notebook_activity_summary(self.team.id, limit=1)
        self.assertEqual(summary.total_count, 2)
        self.assertEqual(len(summary.recent), 1)
        self.assertEqual(summary.recent[0].short_id, newer.short_id)

    @patch("products.notebooks.backend.facade.api.capture_notebook_created")
    def test_create_group_notebook_links_internal_notebook(self, mock_capture):
        data = api.create_group_notebook(self.team.id, group_id=42, title="Notes", content=self._doc())
        self.assertEqual(data.visibility, Notebook.Visibility.INTERNAL)
        self.assertTrue(api.group_has_notebook(42))
        self.assertEqual(api.get_group_notebook_short_id(42), data.short_id)
        self.assertFalse(api.group_has_notebook(43))
        mock_capture.assert_called_once()
        self.assertEqual(mock_capture.call_args.kwargs["creation_source"], NotebookCreationSource.GROUP_AUTO)

    def test_create_account_notebook_and_list_notes(self):
        account = _create_account(self.team)
        data = api.create_account_notebook(
            self.team.id, account.id, title="Recap", content=self._doc(), created_by_id=self.user.id
        )
        self.assertEqual(data.visibility, Notebook.Visibility.INTERNAL)
        self.assertTrue(ResourceNotebook.objects.filter(account=account, notebook_id=data.id).exists())
        notes = api.list_account_internal_notes(account.id)
        self.assertEqual([n.short_id for n in notes], [data.short_id])
        self.assertEqual(notes[0].title, "Recap")

    def test_list_account_notes_excludes_deleted_and_non_internal(self):
        account = _create_account(self.team)
        deleted = Notebook.objects.create(
            team=self.team, title="d", deleted=True, visibility=Notebook.Visibility.INTERNAL
        )
        external = Notebook.objects.create(team=self.team, title="e", visibility=Notebook.Visibility.DEFAULT)
        ResourceNotebook.objects.create(notebook=deleted, account=account)
        ResourceNotebook.objects.create(notebook=external, account=account)
        self.assertEqual(api.list_account_internal_notes(account.id), [])

    def test_account_notebook_crud_surface(self):
        account = _create_account(self.team)
        created = api.create_account_notebook(
            self.team.id, str(account.id), title="Q3", content=self._doc(), created_by_id=self.user.id
        )

        listed = api.list_account_notebooks(str(account.id))
        self.assertEqual([n.short_id for n in listed], [created.short_id])
        self.assertEqual(listed[0].title, "Q3")
        assert listed[0].created_by is not None
        self.assertEqual(listed[0].created_by.id, self.user.id)
        self.assertEqual(listed[0].created_by.email, self.user.email)

        fetched = api.get_account_notebook(str(account.id), created.short_id)
        assert fetched is not None
        self.assertEqual(fetched.short_id, created.short_id)

        self.assertTrue(api.delete_account_notebook(str(account.id), created.short_id))
        self.assertIsNone(api.get_account_notebook(str(account.id), created.short_id))
        self.assertFalse(api.delete_account_notebook(str(account.id), "missing"))

    def test_get_account_notebook_excludes_non_internal(self):
        account = _create_account(self.team)
        external = Notebook.objects.create(team=self.team, title="e", visibility=Notebook.Visibility.DEFAULT)
        ResourceNotebook.objects.create(notebook=external, account=account)
        self.assertEqual(api.list_account_notebooks(str(account.id)), [])
        self.assertIsNone(api.get_account_notebook(str(account.id), external.short_id))


class TestNotebooksFacadeAsync(BaseTest):
    def _doc(self, text: str = "hi") -> dict:
        return {"type": "doc", "content": [content.create_paragraph_with_text(text)]}

    @pytest.mark.asyncio
    async def test_anotebook_exists_and_aget(self):
        notebook = await Notebook.objects.acreate(team=self.team, title="async", content=self._doc())
        self.assertTrue(await api.anotebook_exists(self.team.id, notebook.short_id))
        data = await api.aget_notebook(self.team.id, notebook.short_id)
        assert data is not None
        self.assertEqual(data.short_id, notebook.short_id)

    @pytest.mark.asyncio
    @patch("products.notebooks.backend.facade.api.capture_notebook_created")
    async def test_aupsert_creates_then_overwrites_and_bumps_version(self, mock_capture):
        data, created = await api.aupsert_notebook(
            self.team.id,
            "abc123",
            created_by_id=self.user.id,
            last_modified_by_id=self.user.id,
            title="first",
            content=self._doc("first"),
        )
        self.assertTrue(created)
        self.assertEqual(data.version, 0)
        # Emits `notebook created` once, on the create, labelled max_ai.
        mock_capture.assert_called_once()
        self.assertEqual(mock_capture.call_args.kwargs["creation_source"], NotebookCreationSource.MAX_AI)

        data2, created2 = await api.aupsert_notebook(
            self.team.id,
            "abc123",
            created_by_id=self.user.id,
            last_modified_by_id=self.user.id,
            title="second",
            content=self._doc("second"),
        )
        self.assertFalse(created2)
        self.assertEqual(data2.id, data.id)
        self.assertEqual(data2.title, "second")
        self.assertEqual(data2.version, 1)
        # The overwrite is an update, not a create — no second event (guards double-counting).
        mock_capture.assert_called_once()

    @pytest.mark.asyncio
    async def test_aupdate_notebook_content_bumps_version(self):
        notebook = await Notebook.objects.acreate(team=self.team, short_id="upd123", title="t", content=self._doc())
        data = await api.aupdate_notebook_content(
            self.team.id,
            "upd123",
            content=self._doc("updated"),
            title="t2",
            text_content="updated",
            last_modified_by_id=self.user.id,
        )
        assert data is not None
        self.assertEqual(data.title, "t2")
        self.assertEqual(data.text_content, "updated")
        self.assertEqual(data.version, notebook.version + 1)

    @pytest.mark.asyncio
    async def test_acan_user_edit_notebook_creator(self):
        notebook = await Notebook.objects.acreate(team=self.team, title="t", created_by=self.user)
        uac = UserAccessControl(user=self.user, team=self.team)
        self.assertTrue(await api.acan_user_edit_notebook(self.team.id, notebook.short_id, user_access_control=uac))

    @pytest.mark.asyncio
    async def test_acan_user_edit_missing_notebook(self):
        uac = UserAccessControl(user=self.user, team=self.team)
        self.assertFalse(await api.acan_user_edit_notebook(self.team.id, "missing", user_access_control=uac))


def test_logic_is_internal_only():
    """The facade is the public surface; logic stays an implementation detail."""
    assert hasattr(logic, "create_notebook")
    assert hasattr(api, "create_notebook")
