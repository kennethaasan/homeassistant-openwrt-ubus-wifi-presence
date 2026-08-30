"""Test WiFi device tracker mesh diagnostics."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.openwrt_ubus.const import CONF_HOST, DOMAIN, TRACKER_UNIQUE_ID_PREFIX
from custom_components.openwrt_ubus.data import (
    TrackerTarget,
    TrackerTargetSource,
    TrackerTargetType,
    WifiPresenceDevice,
)
from custom_components.openwrt_ubus.device_tracker import OpenWrtUbusWifiPresenceTrackerManager
from custom_components.openwrt_ubus.device_tracker.wifi_device import OpenWrtUbusWifiPresenceDeviceTracker
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er


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

    assert entity.unique_id == f"{TRACKER_UNIQUE_ID_PREFIX}{target.entity_key}"
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


@pytest.mark.unit
async def test_tracker_manager_adds_one_global_entity_and_migrates_mac_id(hass) -> None:
    """Test three router platforms share one alias-stable tracker entity."""
    target = TrackerTarget(
        entity_key="alias_test_phone",
        tracker_type=TrackerTargetType.ALIAS,
        source=TrackerTargetSource.ALIAS,
        display_name="Test phone",
        mac="11:22:33:44:55:66",
    )
    device = WifiPresenceDevice(
        mac=target.mac,
        ap_device="phy0-ap0",
        ssid="HomeWiFi",
        inactive_ms=20,
    )
    first_entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: "router-office.lan"})
    second_entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: "router-kitchen.lan"})
    first_entry.add_to_hass(hass)
    second_entry.add_to_hass(hass)
    first_entry.runtime_data = SimpleNamespace(coordinator=_coordinator(first_entry, device, target))
    second_entry.runtime_data = SimpleNamespace(coordinator=_coordinator(second_entry, device, target))

    entity_registry = er.async_get(hass)
    legacy = entity_registry.async_get_or_create(
        "device_tracker",
        DOMAIN,
        target.mac,
        config_entry=first_entry,
        suggested_object_id="test_phone",
    )
    manager = OpenWrtUbusWifiPresenceTrackerManager(hass)
    hass.data.setdefault(DOMAIN, {})["wifi_tracker_manager"] = manager
    add_first = MagicMock()
    add_second = MagicMock()

    await manager.async_register_entry(first_entry, add_first)
    add_first.assert_called_once()
    entities = add_first.call_args.args[0]
    assert len(entities) == 1
    entity = entities[0]
    entity.hass = hass
    manager.async_entity_added(entity)

    await manager.async_register_entry(second_entry, add_second)
    add_second.assert_not_called()

    migrated = entity_registry.async_get(legacy.entity_id)
    assert migrated is not None
    assert migrated.entity_id == legacy.entity_id
    assert migrated.unique_id == f"{TRACKER_UNIQUE_ID_PREFIX}{target.entity_key}"
    assert migrated.config_entry_id == first_entry.entry_id


@pytest.mark.unit
async def test_tracker_manager_transfers_entities_when_owner_unloads(hass) -> None:
    """Test the next loaded router takes ownership without duplicate trackers."""
    target = TrackerTarget(
        entity_key="alias_test_phone",
        tracker_type=TrackerTargetType.ALIAS,
        source=TrackerTargetSource.ALIAS,
        display_name="Test phone",
        mac="11:22:33:44:55:66",
    )
    device = WifiPresenceDevice(mac=target.mac, ap_device="phy0-ap0", ssid="HomeWiFi")
    first_entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: "router-office.lan"})
    second_entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: "router-kitchen.lan"})
    first_entry.add_to_hass(hass)
    second_entry.add_to_hass(hass)
    first_entry.runtime_data = SimpleNamespace(coordinator=_coordinator(first_entry, device, target))
    second_entry.runtime_data = SimpleNamespace(coordinator=_coordinator(second_entry, device, target))
    manager = OpenWrtUbusWifiPresenceTrackerManager(hass)
    hass.data.setdefault(DOMAIN, {})["wifi_tracker_manager"] = manager
    add_first = MagicMock()
    add_second = MagicMock()

    await manager.async_register_entry(first_entry, add_first)
    entity = add_first.call_args.args[0][0]
    entity.hass = hass
    manager.async_entity_added(entity)
    await manager.async_register_entry(second_entry, add_second)

    manager._async_unregister_entry(first_entry.entry_id)  # noqa: SLF001
    add_second.assert_not_called()
    manager.async_entity_removed(entity)

    add_second.assert_called_once()
    replacement = add_second.call_args.args[0][0]
    assert replacement.unique_id == entity.unique_id
