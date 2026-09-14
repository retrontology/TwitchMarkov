"""Authorization policy for channel operations.

Pure functions to determine what a user can do based on admin status and channel ownership.
"""

from twitchmarkov.web.sessions import User


def can_view_channel(user: User, channel_id: str) -> bool:
    """Check if a user can view a channel.

    Args:
        user: The user making the request.
        channel_id: The ID of the channel being accessed.

    Returns:
        True if the user is an admin or owns the channel, False otherwise.
    """
    return user.is_admin or user.id == channel_id


def can_edit_channel(user: User, channel_id: str) -> bool:
    """Check if a user can edit a channel.

    Args:
        user: The user making the request.
        channel_id: The ID of the channel being edited.

    Returns:
        True if the user is an admin or owns the channel, False otherwise.
    """
    return user.is_admin or user.id == channel_id


def can_add_channel(user: User, channel_id: str, *, allow_self_service: bool) -> bool:
    """Check if a user can add a channel.

    Args:
        user: The user making the request.
        channel_id: The ID of the channel being added.
        allow_self_service: Whether non-admins are allowed to add their own channels.

    Returns:
        True if the user is an admin or (allow_self_service is True and the user owns the channel).
    """
    return user.is_admin or (allow_self_service and user.id == channel_id)


def can_remove_channel(user: User, channel_id: str, *, allow_self_service: bool) -> bool:
    """Check if a user can remove a channel.

    Args:
        user: The user making the request.
        channel_id: The ID of the channel being removed.
        allow_self_service: Whether non-admins are allowed to remove their own channels.

    Returns:
        True if the user is an admin or (allow_self_service is True and the user owns the channel).
    """
    return user.is_admin or (allow_self_service and user.id == channel_id)


def visible_owner_filter(user: User) -> str | None:
    """Get a filter for visible channel owners based on user permissions.

    Args:
        user: The user requesting the view.

    Returns:
        None if the user is an admin (can see all channels), otherwise the user's ID
        (to filter channels to only those owned by the user).
    """
    return None if user.is_admin else user.id
