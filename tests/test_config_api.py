"""Tests for configuration API endpoints."""
import json
import pytest
from unittest.mock import patch, MagicMock

from inverter import InverterConfig


@pytest.fixture
def client():
    """Create a Flask test client with mocked pollers (configured mode)."""
    import app as app_module

    app_module.app.config["TESTING"] = True

    # Store originals
    orig_inverter_poller = app_module.inverter_poller
    orig_outage_poller = app_module.outage_poller
    orig_weather_poller = app_module.weather_poller
    orig_inverter_config = app_module.inverter_config
    orig_configured = app_module._configured

    # Create mock pollers
    mock_inv_poller = MagicMock()
    mock_weather_poller = MagicMock()

    app_module.inverter_poller = mock_inv_poller
    app_module.weather_poller = mock_weather_poller
    app_module.inverter_config = InverterConfig(phases=3, has_battery=True, pv_strings=2)
    app_module._configured = True

    with app_module.app.test_client() as c:
        yield c, app_module

    # Restore originals
    app_module.inverter_poller = orig_inverter_poller
    app_module.outage_poller = orig_outage_poller
    app_module.weather_poller = orig_weather_poller
    app_module.inverter_config = orig_inverter_config
    app_module._configured = orig_configured


@pytest.fixture
def unconfigured_client():
    """Create a Flask test client in first-run (unconfigured) mode."""
    import app as app_module

    app_module.app.config["TESTING"] = True

    orig_configured = app_module._configured
    app_module._configured = False

    with app_module.app.test_client() as c:
        yield c, app_module

    app_module._configured = orig_configured


class TestConfigStatus:
    def test_configured_status(self, client):
        c, _ = client
        resp = c.get("/api/config/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["configured"] is True
        assert data["first_run"] is False

    def test_unconfigured_status(self, unconfigured_client):
        c, _ = unconfigured_client
        resp = c.get("/api/config/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["configured"] is False
        assert data["first_run"] is True


class TestGetConfig:
    def test_returns_env_values(self, client):
        c, _ = client
        mock_values = {
            "INVERTER_IP": "192.168.1.100",
            "LOGGER_SERIAL": "123456",
            "WEATHER_LATITUDE": "50.4501",
        }
        with patch("setup.load_existing_env", return_value=(mock_values, [])):
            resp = c.get("/api/config")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["INVERTER_IP"] == "192.168.1.100"

    def test_masks_telegram_token(self, client):
        c, _ = client
        mock_values = {
            "TELEGRAM_BOT_TOKEN": "1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ",
        }
        with patch("setup.load_existing_env", return_value=(mock_values, [])):
            resp = c.get("/api/config")
        data = resp.get_json()
        token = data["TELEGRAM_BOT_TOKEN"]
        assert token.startswith("1234")
        assert token.endswith("wxYZ")
        assert "****" in token

    def test_short_token_not_masked(self, client):
        c, _ = client
        mock_values = {"TELEGRAM_BOT_TOKEN": "short"}
        with patch("setup.load_existing_env", return_value=(mock_values, [])):
            resp = c.get("/api/config")
        data = resp.get_json()
        assert data["TELEGRAM_BOT_TOKEN"] == "short"


class TestSaveConfig:
    def test_saves_config_and_returns_ok(self, client):
        c, _ = client
        mock_existing = {"INVERTER_IP": "192.168.1.1", "LOGGER_SERIAL": "111"}
        with patch("setup.load_existing_env", return_value=(mock_existing, [])), \
             patch("setup.write_env") as mock_write, \
             patch("threading.Timer"):
            resp = c.post("/api/config", json={
                "INVERTER_IP": "10.0.0.5",
                "LOGGER_SERIAL": "999",
            })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["restarting"] is True
        # Check merged values
        written_values = mock_write.call_args[0][0]
        assert written_values["INVERTER_IP"] == "10.0.0.5"
        assert written_values["LOGGER_SERIAL"] == "999"

    def test_preserves_masked_token(self, client):
        c, _ = client
        mock_existing = {
            "INVERTER_IP": "192.168.1.1",
            "TELEGRAM_BOT_TOKEN": "realtoken12345678",
        }
        with patch("setup.load_existing_env", return_value=(mock_existing, [])), \
             patch("setup.write_env") as mock_write, \
             patch("threading.Timer"):
            resp = c.post("/api/config", json={
                "INVERTER_IP": "192.168.1.1",
                "TELEGRAM_BOT_TOKEN": "real****5678",
            })
        assert resp.status_code == 200
        written_values = mock_write.call_args[0][0]
        assert written_values["TELEGRAM_BOT_TOKEN"] == "realtoken12345678"

    def test_rejects_invalid_body(self, client):
        c, _ = client
        resp = c.post("/api/config", data="not json",
                       content_type="application/json")
        assert resp.status_code == 400

    def test_preserves_extra_lines(self, client):
        c, _ = client
        extra = ["DEPLOY_HOST=pi.local", "DEPLOY_USER=pi"]
        with patch("setup.load_existing_env", return_value=({}, extra)), \
             patch("setup.write_env") as mock_write, \
             patch("threading.Timer"):
            resp = c.post("/api/config", json={"INVERTER_IP": "1.2.3.4"})
        assert resp.status_code == 200
        written_extra = mock_write.call_args[0][1]
        assert written_extra == extra


class TestConfigDiscover:
    def test_returns_devices(self, client):
        c, _ = client
        mock_devices = [
            {"ip": "192.168.1.100", "model": "SUN-12K-SG04LP3"},
        ]
        with patch("discover_inverter.discover", return_value=mock_devices):
            resp = c.get("/api/config/discover")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["devices"]) == 1
        assert data["devices"][0]["ip"] == "192.168.1.100"

    def test_returns_empty_on_error(self, client):
        c, _ = client
        with patch("discover_inverter.discover", side_effect=Exception("network error")):
            resp = c.get("/api/config/discover")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["devices"] == []


class TestFirstRunGuards:
    def test_api_data_returns_503_when_unconfigured(self, unconfigured_client):
        c, _ = unconfigured_client
        resp = c.get("/api/data")
        assert resp.status_code == 503
        data = resp.get_json()
        assert data["error"] == "not configured"

    def test_api_weather_returns_503_when_unconfigured(self, unconfigured_client):
        c, _ = unconfigured_client
        resp = c.get("/api/weather")
        assert resp.status_code == 503

    def test_generator_returns_disabled_when_unconfigured(self, unconfigured_client):
        c, _ = unconfigured_client
        resp = c.get("/api/generator")
        data = resp.get_json()
        assert data["enabled"] is False

    def test_update_status_returns_defaults_when_unconfigured(self, unconfigured_client):
        c, _ = unconfigured_client
        resp = c.get("/api/update/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["update_available"] is False
        assert data["manager_state"] == "idle"

    def test_index_serves_page_when_unconfigured(self, unconfigured_client):
        c, _ = unconfigured_client
        resp = c.get("/")
        assert resp.status_code == 200


class TestIsConfigured:
    def test_unconfigured_defaults(self):
        from app import is_configured
        with patch.dict("os.environ", {"INVERTER_IP": "0.0.0.0", "LOGGER_SERIAL": "0"}):
            assert is_configured() is False

    def test_configured_values(self):
        from app import is_configured
        with patch.dict("os.environ", {"INVERTER_IP": "192.168.1.100", "LOGGER_SERIAL": "123456"}):
            assert is_configured() is True

    def test_empty_values(self):
        from app import is_configured
        with patch.dict("os.environ", {"INVERTER_IP": "", "LOGGER_SERIAL": ""}, clear=False):
            assert is_configured() is False

    def test_missing_values(self):
        from app import is_configured
        env = dict(__builtins__="") # dummy to use clear
        with patch.dict("os.environ", {}, clear=True):
            assert is_configured() is False
