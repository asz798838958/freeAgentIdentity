"""Unified provider plugin system.

All provider implementations (mailbox, captcha, proxy) live under this
package.  Call ``providers.registry.load_all()`` once at application startup
to auto-discover every provider module and populate the global registry.
"""
