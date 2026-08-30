"""Sensor platform for OpenWrt Ubus WiFi Presence."""

from __future__ import annotations

from custom_components.openwrt_ubus.data import OpenWrtUbusWifiPresenceConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .router import ROUTER_SENSOR_DESCRIPTIONS, OpenWrtUbusRouterSensor


async def async_setup_entry(
    hass,
    entry: OpenWrtUbusWifiPresenceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up router metric sensors for one config entry."""
    del hass
    async_add_entities(OpenWrtUbusRouterSensor(entry, description) for description in ROUTER_SENSOR_DESCRIPTIONS)
