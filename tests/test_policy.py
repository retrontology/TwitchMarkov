"""Authorization policy tests."""

import pytest

from twitchmarkov.web.policy import (
    can_add_channel,
    can_edit_channel,
    can_remove_channel,
    can_view_channel,
    visible_owner_filter,
)
from twitchmarkov.web.sessions import User


def _user(id: str, is_admin: bool) -> User:
    """Build a user for testing."""
    return User(id=id, login=id, display_name=id.capitalize(), is_admin=is_admin)


class TestCanViewChannel:
    """Tests for can_view_channel."""

    @pytest.mark.parametrize("user,channel_id,expected", [
        # Admin can view any channel
        (_user("admin", is_admin=True), "some_channel", True),
        # Owner can view their own channel
        (_user("owner", is_admin=False), "owner", True),
        # Stranger cannot view others' channels
        (_user("stranger", is_admin=False), "owner", False),
    ])
    def test_can_view_channel(self, user, channel_id, expected):
        assert can_view_channel(user, channel_id) is expected


class TestCanEditChannel:
    """Tests for can_edit_channel."""

    @pytest.mark.parametrize("user,channel_id,expected", [
        # Admin can edit any channel
        (_user("admin", is_admin=True), "some_channel", True),
        # Owner can edit their own channel
        (_user("owner", is_admin=False), "owner", True),
        # Stranger cannot edit others' channels
        (_user("stranger", is_admin=False), "owner", False),
    ])
    def test_can_edit_channel(self, user, channel_id, expected):
        assert can_edit_channel(user, channel_id) is expected


class TestCanAddChannel:
    """Tests for can_add_channel."""

    @pytest.mark.parametrize("user,channel_id,allow_self_service,expected", [
        # Admin can add any channel, regardless of allow_self_service
        (_user("admin", is_admin=True), "some_channel", True, True),
        (_user("admin", is_admin=True), "some_channel", False, True),
        # Owner can add their own channel only when allow_self_service=True
        (_user("owner", is_admin=False), "owner", True, True),
        (_user("owner", is_admin=False), "owner", False, False),
        # Stranger cannot add channels
        (_user("stranger", is_admin=False), "owner", True, False),
        (_user("stranger", is_admin=False), "owner", False, False),
    ])
    def test_can_add_channel(self, user, channel_id, allow_self_service, expected):
        assert can_add_channel(user, channel_id, allow_self_service=allow_self_service) is expected


class TestCanRemoveChannel:
    """Tests for can_remove_channel."""

    @pytest.mark.parametrize("user,channel_id,allow_self_service,expected", [
        # Admin can remove any channel, regardless of allow_self_service
        (_user("admin", is_admin=True), "some_channel", True, True),
        (_user("admin", is_admin=True), "some_channel", False, True),
        # Owner can remove their own channel only when allow_self_service=True
        (_user("owner", is_admin=False), "owner", True, True),
        (_user("owner", is_admin=False), "owner", False, False),
        # Stranger cannot remove channels
        (_user("stranger", is_admin=False), "owner", True, False),
        (_user("stranger", is_admin=False), "owner", False, False),
    ])
    def test_can_remove_channel(self, user, channel_id, allow_self_service, expected):
        assert can_remove_channel(user, channel_id, allow_self_service=allow_self_service) is expected


class TestVisibleOwnerFilter:
    """Tests for visible_owner_filter."""

    @pytest.mark.parametrize("user,expected", [
        # Admin can see all (None means no filter)
        (_user("admin", is_admin=True), None),
        # Non-admin sees only their own (returns user.id)
        (_user("owner", is_admin=False), "owner"),
        (_user("stranger", is_admin=False), "stranger"),
    ])
    def test_visible_owner_filter(self, user, expected):
        assert visible_owner_filter(user) is expected
