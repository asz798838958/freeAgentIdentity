from platforms._browser_backend import BrowserBackendConfig
from platforms.chatgpt.browser_register import _apply_camoufox_visible_window_limit


def test_apply_camoufox_visible_window_limit_sets_1280_by_720_window_for_headed_camoufox():
    launch_opts = {"headless": False}

    _apply_camoufox_visible_window_limit(
        launch_opts,
        BrowserBackendConfig.camoufox(headless=False),
    )

    assert launch_opts["window"] == (1280, 720)


def test_apply_camoufox_visible_window_limit_skips_headless_camoufox():
    launch_opts = {"headless": True}

    _apply_camoufox_visible_window_limit(
        launch_opts,
        BrowserBackendConfig.camoufox(headless=True),
    )

    assert "window" not in launch_opts


def test_apply_camoufox_visible_window_limit_skips_bitbrowser():
    launch_opts = {"headless": False}

    _apply_camoufox_visible_window_limit(
        launch_opts,
        BrowserBackendConfig.bitbrowser(profile_id="profile-1"),
    )

    assert "window" not in launch_opts
