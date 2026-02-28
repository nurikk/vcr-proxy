from vcr_proxy.config import Settings
from vcr_proxy.models import ProxyMode


def test_default_settings():
    settings = Settings()
    assert settings.mode == ProxyMode.SPY
    assert settings.port == 8080
    assert settings.admin_port == 8081
    assert "date" in settings.always_ignore_headers


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("VCR_MODE", "record")
    monkeypatch.setenv("VCR_PORT", "9090")
    monkeypatch.setenv("VCR_TARGET", "https://api.example.com")
    settings = Settings()
    assert settings.mode == ProxyMode.RECORD
    assert settings.port == 9090
    assert settings.target == "https://api.example.com"


def test_settings_targets_mapping():
    settings = Settings(targets={"/api": "https://api.example.com"})
    assert settings.targets["/api"] == "https://api.example.com"


def test_settings_cassettes_dir_default():
    settings = Settings()
    assert str(settings.cassettes_dir) == "cassettes"


def test_forward_proxy_defaults():
    settings = Settings()
    assert settings.forward_proxy_port == 8888
    assert settings.mitm_confdir is None


def test_forward_proxy_port_from_env(monkeypatch):
    monkeypatch.setenv("VCR_FORWARD_PROXY_PORT", "9999")
    settings = Settings()
    assert settings.forward_proxy_port == 9999
