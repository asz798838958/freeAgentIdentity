"""Email + API URL mailbox provider registration."""

from core.api_mailbox import ApiMailboxPool  # noqa: F401
from providers.registry import register_provider


register_provider("mailbox", "api_mailbox")(ApiMailboxPool)
