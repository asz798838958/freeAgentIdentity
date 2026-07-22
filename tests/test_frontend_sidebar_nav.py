from pathlib import Path


APP_TSX = Path(__file__).resolve().parents[1] / "frontend" / "src" / "App.tsx"


def _nav_items_block() -> str:
    source = APP_TSX.read_text(encoding="utf-8")
    start = source.index("const NAV_ITEMS: NavItem[] = [")
    end = source.index("];", start)
    return source[start:end]


def test_sidebar_top_level_nav_keeps_dashboard_chatgpt_and_settings():
    block = _nav_items_block()

    assert block.count("path:") == 3
    assert 'path: "/"' in block
    assert 'labelKey: "nav.dashboard"' in block
    assert 'path: "/accounts/chatgpt"' in block
    assert 'label: "chatgpt free"' in block
    assert 'path: "/settings"' in block
    assert 'labelKey: "nav.settings"' in block


def test_sidebar_hides_accounts_menu_and_other_business_links():
    source = APP_TSX.read_text(encoding="utf-8")

    assert "setAccountsOpen" not in source
    assert "getPlatforms" not in source
    assert "nav.accounts" not in source
    assert "nav.ctfGptPlus" not in source
    assert "nav.gopayGptPlus" not in source
    assert "nav.plusManager" not in source
    assert "nav.tasks" not in source


def test_sidebar_only_keeps_general_and_mailbox_settings_submenu_items():
    source = APP_TSX.read_text(encoding="utf-8")

    start = source.index("const SETTINGS_NAV_ITEMS:")
    end = source.index("];", start)
    block = source[start:end]

    assert block.count('hash: "') == 2
    assert 'labelKey: "nav.settings.general", hash: "general"' in block
    assert 'labelKey: "nav.settings.mailbox", hash: "mailbox"' in block

    assert "currentTab" in source
    assert "/settings?tab=${item.hash}" in source
