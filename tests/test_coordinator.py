from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.openwrt_ubus.api import (
    OpenWrtUbusAuthenticationError,
    OpenWrtUbusClient,
    OpenWrtUbusCommunicationError,
)
from custom_components.openwrt_ubus.const import (
    CONF_ENDPOINT,
    CONF_IP_ADDRESS,
    CONF_SCAN_INTERVAL,
    CONF_TRACKING_MODE,
    CONF_USE_HTTPS,
    DOMAIN,
)
from custom_components.openwrt_ubus.coordinator import OpenWrtUbusWifiPresenceCoordinator
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed


@pytest.mark.unit
async def test_coordinator_raises_config_entry_auth_failed_on_auth_error(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="ap-livingroom.example.com",
        data={
            CONF_HOST: "ap-livingroom.example.com",
            CONF_IP_ADDRESS: "",
            CONF_USE_HTTPS: False,
            CONF_PORT: None,
            CONF_VERIFY_SSL: False,
            CONF_ENDPOINT: "ubus",
            CONF_USERNAME: "root",
            CONF_PASSWORD: "secret",
            CONF_TRACKING_MODE: "known_or_alias",
            CONF_SCAN_INTERVAL: 30,
        },
    )

    client = AsyncMock()
    client.normalize_mac = OpenWrtUbusClient.normalize_mac
    client.get_wifi_ssid_inventory.side_effect = OpenWrtUbusAuthenticationError("invalid credentials")

    coordinator = OpenWrtUbusWifiPresenceCoordinator(hass=hass, entry=entry, client=client)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()  # noqa: SLF001


@pytest.mark.unit
@pytest.mark.parametrize("inventory_complete", [True, False])
async def test_coordinator_filters_unauthorized_stations(hass, inventory_complete: bool) -> None:
    """Test station filtering while preserving WiFi SSID inventory quality."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="router-office.example.com",
        data={
            CONF_HOST: "router-office.example.com",
            CONF_IP_ADDRESS: "",
            CONF_USE_HTTPS: False,
            CONF_PORT: None,
            CONF_VERIFY_SSL: False,
            CONF_ENDPOINT: "ubus",
            CONF_USERNAME: "root",
            CONF_PASSWORD: "secret",
            CONF_TRACKING_MODE: "all",
            CONF_SCAN_INTERVAL: 30,
        },
    )

    client = AsyncMock()
    client.normalize_mac = OpenWrtUbusClient.normalize_mac
    client.get_wifi_ssid_inventory.return_value = (
        {"wlan0": "HomeWiFi"},
        {"HomeWiFi", "DisabledWiFi"},
        inventory_complete,
    )
    client.get_iwinfo_ap_devices.return_value = ["wlan0"]
    client.get_iwinfo_assoclist.return_value = [
        {
            "mac": "11:22:33:44:55:66",
            "signal": -50,
            "signal_avg": -52,
            "noise": -95,
            "inactive": 70,
            "connected_time": 3600,
            "rx": {"rate": 866700},
            "tx": {"rate": 144400},
            "authorized": True,
        },
        {
            "mac": "AA:BB:CC:DD:EE:FF",
            "signal": -46,
            "inactive": 11550,
            "authorized": False,
        },
    ]

    coordinator = OpenWrtUbusWifiPresenceCoordinator(hass=hass, entry=entry, client=client)
    devices = await coordinator._async_update_data()  # noqa: SLF001

    assert "11:22:33:44:55:66" in devices
    assert "AA:BB:CC:DD:EE:FF" not in devices
    station = devices["11:22:33:44:55:66"]
    assert station.signal_dbm == -50
    assert station.signal_average_dbm == -52
    assert station.noise_dbm == -95
    assert station.inactive_ms == 70
    assert station.connected_time_seconds == 3600
    assert station.rx_rate_mbps == 866.7
    assert station.tx_rate_mbps == 144.4
    assert coordinator.known_ssids == {"HomeWiFi", "DisabledWiFi"}
    assert coordinator.ssid_inventory_complete is inventory_complete


@pytest.mark.unit
async def test_coordinator_prefers_fresh_duplicate_radio_association(hass) -> None:
    """Test one router reporting a roaming station on two radios."""
    client = AsyncMock()
    client.normalize_mac = OpenWrtUbusClient.normalize_mac
    client.get_wifi_ssid_inventory.return_value = (
        {"phy0-ap0": "HomeWiFi", "phy1-ap0": "HomeWiFi"},
        {"HomeWiFi"},
        True,
    )
    client.get_iwinfo_ap_devices.return_value = ["phy0-ap0", "phy1-ap0"]
    client.get_iwinfo_assoclist.side_effect = [
        [{"mac": "11:22:33:44:55:66", "signal": -44, "inactive": 800}],
        [{"mac": "11:22:33:44:55:66", "signal": -62, "inactive": 20}],
    ]

    coordinator = OpenWrtUbusWifiPresenceCoordinator(
        hass=hass,
        entry=_fallback_test_entry(),
        client=client,
    )
    devices = await coordinator._async_update_data()  # noqa: SLF001

    assert devices["11:22:33:44:55:66"].ap_device == "phy1-ap0"
    assert devices["11:22:33:44:55:66"].inactive_ms == 20


def _fallback_test_entry() -> MockConfigEntry:
    """Build a config entry for SSID fallback completeness tests."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="router-fallback.example.com",
        data={
            CONF_HOST: "router-fallback.example.com",
            CONF_IP_ADDRESS: "",
            CONF_USE_HTTPS: False,
            CONF_PORT: None,
            CONF_VERIFY_SSL: False,
            CONF_ENDPOINT: "ubus",
            CONF_USERNAME: "root",
            CONF_PASSWORD: "secret",
            CONF_TRACKING_MODE: "all",
            CONF_SCAN_INTERVAL: 30,
        },
    )


@pytest.mark.unit
async def test_coordinator_marks_observed_fallback_inventory_complete(hass) -> None:
    """Test that a successfully resolved observed-only SSID is authoritative."""
    client = AsyncMock()
    client.normalize_mac = OpenWrtUbusClient.normalize_mac
    client.get_wifi_ssid_inventory.return_value = ({"wlan0": "HomeWiFi"}, {"HomeWiFi"}, True)
    client.get_iwinfo_ap_devices.return_value = ["wlan0", "wlan1"]
    client.get_iwinfo_assoclist.return_value = []
    client.get_iwinfo_ssid.return_value = "GuestWiFi"

    coordinator = OpenWrtUbusWifiPresenceCoordinator(hass=hass, entry=_fallback_test_entry(), client=client)
    await coordinator._async_update_data()  # noqa: SLF001

    assert coordinator.known_ssids == {"HomeWiFi", "GuestWiFi"}
    assert coordinator.ssid_inventory_complete is True
    client.get_iwinfo_ssid.assert_awaited_once_with("wlan1")


@pytest.mark.unit
async def test_coordinator_marks_missing_observed_fallback_incomplete(hass) -> None:
    """Test that an unresolved fallback SSID blocks destructive cleanup."""
    client = AsyncMock()
    client.normalize_mac = OpenWrtUbusClient.normalize_mac
    client.get_wifi_ssid_inventory.return_value = ({"wlan0": "HomeWiFi"}, {"HomeWiFi"}, True)
    client.get_iwinfo_ap_devices.return_value = ["wlan0", "wlan1"]
    client.get_iwinfo_assoclist.return_value = []
    client.get_iwinfo_ssid.return_value = None

    coordinator = OpenWrtUbusWifiPresenceCoordinator(hass=hass, entry=_fallback_test_entry(), client=client)
    await coordinator._async_update_data()  # noqa: SLF001

    assert coordinator.known_ssids == {"HomeWiFi"}
    assert coordinator.ssid_inventory_complete is False


@pytest.mark.unit
async def test_coordinator_fails_refresh_on_observed_fallback_error(hass) -> None:
    """Test that an iwinfo SSID communication error fails the coordinator refresh."""
    client = AsyncMock()
    client.normalize_mac = OpenWrtUbusClient.normalize_mac
    client.get_wifi_ssid_inventory.return_value = ({"wlan0": "HomeWiFi"}, {"HomeWiFi"}, True)
    client.get_iwinfo_ap_devices.return_value = ["wlan0", "wlan1"]
    client.get_iwinfo_assoclist.return_value = []
    client.get_iwinfo_ssid.side_effect = OpenWrtUbusCommunicationError("temporary failure")

    coordinator = OpenWrtUbusWifiPresenceCoordinator(hass=hass, entry=_fallback_test_entry(), client=client)

    with pytest.raises(UpdateFailed, match="temporary failure"):
        await coordinator._async_update_data()  # noqa: SLF001
