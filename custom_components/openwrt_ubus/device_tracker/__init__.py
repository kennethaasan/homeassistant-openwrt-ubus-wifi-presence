"""Device tracker platform for OpenWrt Ubus WiFi Presence."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from custom_components.openwrt_ubus.const import CONF_HOST, DOMAIN, TRACKER_UNIQUE_ID_PREFIX
from custom_components.openwrt_ubus.coordinator import OpenWrtUbusWifiPresenceCoordinator
from custom_components.openwrt_ubus.data import (
    OpenWrtUbusWifiPresenceConfigEntry,
    TrackerTarget,
    WifiPresenceDevice,
    association_preference,
)
from custom_components.openwrt_ubus.device_tracker.wifi_device import OpenWrtUbusWifiPresenceDeviceTracker
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

_TRACKER_MANAGER_KEY = "wifi_tracker_manager"


def _tracker_unique_id(entity_key: str) -> str:
    """Return the stable global unique ID for one tracker target."""
    return f"{TRACKER_UNIQUE_ID_PREFIX}{entity_key}"


def _extract_entity_key(unique_id: str, hosts: set[str]) -> str | None:
    """Extract an integration entity key from current or intended legacy IDs."""
    if unique_id.startswith(TRACKER_UNIQUE_ID_PREFIX):
        return unique_id.removeprefix(TRACKER_UNIQUE_ID_PREFIX)

    for host in hosts:
        prefix = f"{host}_"
        if unique_id.startswith(prefix):
            return unique_id.removeprefix(prefix)
    return None


def _registry_entries_by_key(
    entity_registry: er.EntityRegistry,
    hosts: set[str],
) -> dict[str, er.RegistryEntry]:
    """Return global tracker registry entries indexed by entity key."""
    entries_by_key: dict[str, er.RegistryEntry] = {}
    for existing in entity_registry.entities.values():
        if existing.domain != "device_tracker" or existing.platform != DOMAIN or not existing.unique_id:
            continue
        entity_key = _extract_entity_key(existing.unique_id, hosts)
        if entity_key is not None:
            entries_by_key[entity_key] = existing
    return entries_by_key


def _sync_registry_visibility(
    entity_registry: er.EntityRegistry,
    entries_by_key: Mapping[str, er.RegistryEntry],
    desired_keys: set[str],
) -> None:
    """Enable desired entries and disable entries outside the current filter."""
    for entity_key, registry_entry in entries_by_key.items():
        if registry_entry.disabled_by not in (None, er.RegistryEntryDisabler.INTEGRATION):
            continue
        if registry_entry.hidden_by not in (None, er.RegistryEntryHider.INTEGRATION):
            continue

        should_be_enabled = entity_key in desired_keys
        if should_be_enabled:
            clear_disabled = registry_entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION
            clear_hidden = registry_entry.hidden_by == er.RegistryEntryHider.INTEGRATION
            if clear_disabled and clear_hidden:
                entity_registry.async_update_entity(registry_entry.entity_id, disabled_by=None, hidden_by=None)
            elif clear_disabled:
                entity_registry.async_update_entity(registry_entry.entity_id, disabled_by=None)
            elif clear_hidden:
                entity_registry.async_update_entity(registry_entry.entity_id, hidden_by=None)
        else:
            set_disabled = registry_entry.disabled_by is None
            set_hidden = registry_entry.hidden_by is None
            if set_disabled and set_hidden:
                entity_registry.async_update_entity(
                    registry_entry.entity_id,
                    disabled_by=er.RegistryEntryDisabler.INTEGRATION,
                    hidden_by=er.RegistryEntryHider.INTEGRATION,
                )
            elif set_disabled:
                entity_registry.async_update_entity(
                    registry_entry.entity_id,
                    disabled_by=er.RegistryEntryDisabler.INTEGRATION,
                )
            elif set_hidden:
                entity_registry.async_update_entity(
                    registry_entry.entity_id,
                    hidden_by=er.RegistryEntryHider.INTEGRATION,
                )


class OpenWrtUbusWifiPresenceTrackerManager:
    """Manage one global tracker per target across all OpenWrt entries."""

    def __init__(self, hass) -> None:
        """Initialize the global tracker manager."""
        self.hass = hass
        self._entities_by_key: dict[str, OpenWrtUbusWifiPresenceDeviceTracker] = {}
        self._pending_keys: set[str] = set()
        self._coordinators: dict[str, OpenWrtUbusWifiPresenceCoordinator] = {}
        self._coordinator_unsubscribes: dict[str, Callable[[], None]] = {}
        self._async_add_entities_by_entry: dict[str, AddEntitiesCallback] = {}
        self._entries: dict[str, OpenWrtUbusWifiPresenceConfigEntry] = {}
        self._owner_entry_id: str | None = None

    @property
    def tracker_targets(self) -> dict[str, TrackerTarget]:
        """Return the union of tracker targets configured on loaded routers."""
        targets: dict[str, TrackerTarget] = {}
        for coordinator in self._coordinators.values():
            for entity_key, target in coordinator.tracker_targets.items():
                targets.setdefault(entity_key, target)
        return targets

    @property
    def hosts(self) -> set[str]:
        """Return all currently registered OpenWrt hosts."""
        return {entry.data[CONF_HOST] for entry in self._entries.values()}

    def find_device(self, mac: str) -> tuple[WifiPresenceDevice | None, str | None]:
        """Find the freshest association for one MAC across every router."""
        candidates: list[tuple[WifiPresenceDevice, str]] = []
        for entry_id, coordinator in self._coordinators.items():
            device = coordinator.data.get(mac)
            if device is None:
                continue
            candidates.append((device, self._entries[entry_id].data[CONF_HOST]))

        if not candidates:
            return None, None
        return min(candidates, key=lambda candidate: association_preference(candidate[0]))

    async def async_register_entry(
        self,
        entry: OpenWrtUbusWifiPresenceConfigEntry,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        """Register one config entry and its coordinator."""
        self._entries[entry.entry_id] = entry
        self._async_add_entities_by_entry[entry.entry_id] = async_add_entities
        if self._owner_entry_id is None:
            self._owner_entry_id = entry.entry_id

        if entry.entry_id in self._coordinator_unsubscribes:
            self._sync_tracker_entities()
            return

        coordinator = entry.runtime_data.coordinator
        self._coordinators[entry.entry_id] = coordinator
        self._coordinator_unsubscribes[entry.entry_id] = coordinator.async_add_listener(self._handle_coordinator_update)
        entry.async_on_unload(lambda: self._async_unregister_entry(entry.entry_id))
        self._sync_tracker_entities()

    def _async_unregister_entry(self, entry_id: str) -> None:
        """Unregister one config entry and transfer tracker ownership if needed."""
        if unsubscribe := self._coordinator_unsubscribes.pop(entry_id, None):
            unsubscribe()
        self._coordinators.pop(entry_id, None)
        self._async_add_entities_by_entry.pop(entry_id, None)
        self._entries.pop(entry_id, None)
        if self._owner_entry_id == entry_id:
            self._owner_entry_id = next(iter(self._async_add_entities_by_entry), None)
        self._sync_tracker_entities()

    @callback
    def async_entity_added(self, entity: OpenWrtUbusWifiPresenceDeviceTracker) -> None:
        """Track an entity only after Home Assistant accepted it."""
        self._pending_keys.discard(entity.entity_key)
        self._entities_by_key[entity.entity_key] = entity

    @callback
    def async_entity_removed(self, entity: OpenWrtUbusWifiPresenceDeviceTracker) -> None:
        """Stop tracking an entity removed by Home Assistant."""
        if self._entities_by_key.get(entity.entity_key) is entity:
            self._entities_by_key.pop(entity.entity_key)
            if self._owner_entry_id != entity.owner_entry_id:
                self._sync_tracker_entities()

    def _legacy_registry_entry(
        self,
        entity_registry: er.EntityRegistry,
        target: TrackerTarget,
    ) -> er.RegistryEntry | None:
        """Find a tracker registered with the old MAC or host-specific ID."""
        candidate_ids = {f"{host}_{target.entity_key}" for host in self.hosts}
        if target.mac:
            candidate_ids.add(target.mac)

        casefolded_ids = {candidate.casefold() for candidate in candidate_ids}
        for existing in entity_registry.entities.values():
            if (
                existing.domain == "device_tracker"
                and existing.platform == DOMAIN
                and existing.unique_id.casefold() in casefolded_ids
            ):
                return existing
        return None

    def _migrate_registry_entries(self, targets: Mapping[str, TrackerTarget]) -> None:
        """Migrate legacy per-MAC IDs and move entities to the active owner."""
        if self._owner_entry_id is None:
            return

        entity_registry = er.async_get(self.hass)
        for entity_key, target in targets.items():
            unique_id = _tracker_unique_id(entity_key)
            entity_id = entity_registry.async_get_entity_id("device_tracker", DOMAIN, unique_id)
            registry_entry = entity_registry.async_get(entity_id) if entity_id else None
            if registry_entry is None:
                registry_entry = self._legacy_registry_entry(entity_registry, target)
                if registry_entry is not None:
                    entity_registry.async_update_entity(
                        registry_entry.entity_id,
                        config_entry_id=self._owner_entry_id,
                        new_unique_id=unique_id,
                    )
            elif registry_entry.config_entry_id != self._owner_entry_id:
                entity_registry.async_update_entity(
                    registry_entry.entity_id,
                    config_entry_id=self._owner_entry_id,
                )

    def _tracker_entity_needs_add(
        self,
        entity_registry: er.EntityRegistry,
        entity_key: str,
    ) -> bool:
        """Return whether Home Assistant should process this tracker entity."""
        if entity_key in self._entities_by_key or entity_key in self._pending_keys:
            return False

        entity_id = entity_registry.async_get_entity_id(
            "device_tracker",
            DOMAIN,
            _tracker_unique_id(entity_key),
        )
        if entity_id is None:
            return True
        registry_entry = entity_registry.async_get(entity_id)
        return bool(registry_entry and not registry_entry.disabled)

    def _sync_tracker_entities(self) -> None:
        """Reconcile global trackers with all currently configured targets."""
        if self._owner_entry_id is None:
            return
        async_add_entities = self._async_add_entities_by_entry.get(self._owner_entry_id)
        owner_entry = self._entries.get(self._owner_entry_id)
        owner_coordinator = self._coordinators.get(self._owner_entry_id)
        if async_add_entities is None or owner_entry is None or owner_coordinator is None:
            return

        targets = self.tracker_targets
        self._migrate_registry_entries(targets)
        entity_registry = er.async_get(self.hass)
        entries_by_key = _registry_entries_by_key(entity_registry, self.hosts)
        _sync_registry_visibility(entity_registry, entries_by_key, set(targets))

        new_entities: list[OpenWrtUbusWifiPresenceDeviceTracker] = []
        for entity_key in sorted(targets):
            if not self._tracker_entity_needs_add(entity_registry, entity_key):
                continue
            entity = OpenWrtUbusWifiPresenceDeviceTracker(
                owner_coordinator,
                owner_entry,
                entity_key,
                manager=self,
            )
            self._pending_keys.add(entity_key)
            entity.async_on_remove(lambda entity_key=entity_key: self._pending_keys.discard(entity_key))
            new_entities.append(entity)

        if new_entities:
            async_add_entities(new_entities)

    def _handle_coordinator_update(self) -> None:
        """Reconcile entities and publish global association changes."""
        self._sync_tracker_entities()
        for entity in self._entities_by_key.values():
            entity.async_write_ha_state()


def _get_manager(hass) -> OpenWrtUbusWifiPresenceTrackerManager | None:
    """Return the global WiFi tracker manager when initialized."""
    domain_data = hass.data.get(DOMAIN)
    if not isinstance(domain_data, Mapping):
        return None
    manager = domain_data.get(_TRACKER_MANAGER_KEY)
    if isinstance(manager, OpenWrtUbusWifiPresenceTrackerManager):
        return manager
    return None


async def async_setup_entry(
    hass,
    entry: OpenWrtUbusWifiPresenceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up global WiFi device trackers across every OpenWrt entry."""
    manager = _get_manager(hass)
    if manager is None:
        manager = OpenWrtUbusWifiPresenceTrackerManager(hass)
        hass.data.setdefault(DOMAIN, {})[_TRACKER_MANAGER_KEY] = manager

    await manager.async_register_entry(entry, async_add_entities)
