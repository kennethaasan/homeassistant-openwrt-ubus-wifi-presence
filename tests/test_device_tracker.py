"""Test WiFi device tracker mesh diagnostics."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.openwrt_ubus.const import CONF_HOST
from custom_components.openwrt_ubus.data import (
    TrackerTarget,
    TrackerTargetSource,
    TrackerTargetType,
    WifiPresenceDevice,
)
from custom_components.openwrt_ubus.device_tracker.wifi_device import OpenWrtUbusWifiPresenceDeviceTracker
from homeassistant.config_entries import ConfigEntryState


def _coordinator(entry, device: WifiPresenceDevice, target: TrackerTarget):
    """Build a coordinator mock containing one station and target."""
    return SimpleNamespace(
        data={target.mac: device},
        entry=entry,
        last_update_success=True,
        tracker_targets={target.entity_key: target},
        async_add_listener=MagicMock(),
    )


@pytest.mark.unit
def test_tracker_prefers_fresh_mesh_association_and_exposes_radio_metrics() -> None:
    """Test duplicate mesh associations use freshness before signal strength."""
    target = TrackerTarget(
        entity_key="alias_test_phone",
        tracker_type=TrackerTargetType.ALIAS,
        source=TrackerTargetSource.ALIAS,
        display_name="Test phone",
        mac="11:22:33:44:55:66",
    )
    local_entry = SimpleNamespace(
        data={CONF_HOST: "router-office.lan"},
        entry_id="local-entry",
    )
    remote_entry = SimpleNamespace(
        data={CONF_HOST: "router-kitchen.lan"},
        entry_id="remote-entry",
        state=ConfigEntryState.LOADED,
    )
    local_device = WifiPresenceDevice(
        mac=target.mac,
        ap_device="phy0-ap0",
        ssid="HomeWiFi",
        signal_dbm=-45,
        noise_dbm=-95,
        inactive_ms=900,
    )
    remote_device = WifiPresenceDevice(
        mac=target.mac,
        ap_device="phy1-ap0",
        ssid="HomeWiFi",
        signal_dbm=-61,
        signal_average_dbm=-63,
        noise_dbm=-96,
        inactive_ms=20,
        connected_time_seconds=7200,
        rx_rate_mbps=432.1,
        tx_rate_mbps=144.4,
    )
    local_coordinator = _coordinator(local_entry, local_device, target)
    remote_entry.runtime_data = SimpleNamespace(coordinator=_coordinator(remote_entry, remote_device, target))
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_entries=MagicMock(return_value=[remote_entry]),
        )
    )

    entity = OpenWrtUbusWifiPresenceDeviceTracker(
        local_coordinator,
        local_entry,
        target.entity_key,
    )
    entity.hass = hass

    assert entity.is_connected is True
    assert entity.extra_state_attributes == {
        "router": "router-kitchen.lan",
        "entity_key": "alias_test_phone",
        "tracker_type": "alias",
        "target_source": "alias",
        "mapped_mac": "11:22:33:44:55:66",
        "mapping_exists": True,
        "ssid": "HomeWiFi",
        "ap_device": "phy1-ap0",
        "signal_dbm": -61,
        "signal_average_dbm": -63,
        "noise_dbm": -96,
        "snr_db": 35,
        "inactive_ms": 20,
        "connected_time_seconds": 7200,
        "rx_rate_mbps": 432.1,
        "tx_rate_mbps": 144.4,
    }
