"""Test router diagnostic sensors."""

from __future__ import annotations

import pytest

from custom_components.openwrt_ubus.data import WifiPresenceDevice
from custom_components.openwrt_ubus.sensor.router import ROUTER_SENSOR_DESCRIPTIONS


@pytest.mark.unit
def test_router_sensor_descriptions_summarize_associated_stations() -> None:
    """Test client count and signal summaries."""
    devices = {
        "11:22:33:44:55:66": WifiPresenceDevice(
            mac="11:22:33:44:55:66",
            ap_device="phy0-ap0",
            ssid="HomeWiFi",
            signal_dbm=-47,
        ),
        "AA:BB:CC:DD:EE:FF": WifiPresenceDevice(
            mac="AA:BB:CC:DD:EE:FF",
            ap_device="phy1-ap0",
            ssid="HomeWiFi",
            signal_dbm=-73,
        ),
    }
    values = {description.key: description.value_fn(devices) for description in ROUTER_SENSOR_DESCRIPTIONS}

    assert values == {
        "associated_clients": 2,
        "average_station_signal": -60.0,
        "weakest_station_signal": -73,
    }


@pytest.mark.unit
def test_router_signal_sensors_handle_no_measurements() -> None:
    """Test signal summaries remain unknown when iwinfo omits radio metrics."""
    devices = {
        "11:22:33:44:55:66": WifiPresenceDevice(
            mac="11:22:33:44:55:66",
            ap_device="phy0-ap0",
            ssid="HomeWiFi",
        )
    }
    values = {description.key: description.value_fn(devices) for description in ROUTER_SENSOR_DESCRIPTIONS}

    assert values["associated_clients"] == 1
    assert values["average_station_signal"] is None
    assert values["weakest_station_signal"] is None
