"""Local Microsoft mailbox pool — register into unified registry."""
from core.local_ms_mailbox import LocalMicrosoftMailboxPool  # noqa: F401
from providers.registry import register_provider

register_provider("mailbox", "local_ms_pool")(LocalMicrosoftMailboxPool)
