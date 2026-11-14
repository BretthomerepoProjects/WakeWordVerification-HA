"""Configure enrolled satellites over their ESPHome action."""
import asyncio
import logging

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry, entity_registry
from homeassistant.helpers.network import get_url, NoURLAvailableError

_LOGGER = logging.getLogger(__name__)
PATH = "/api/wake_word_verification/v1/verify"


def node_action(hass, entity_id):
    entity = entity_registry.async_get(hass).async_get(entity_id)
    if not entity or not entity.device_id:
        return None
    device = device_registry.async_get(hass).async_get(entity.device_id)
    if not device:
        return None
    entries = [
        entry for entry_id in device.config_entries
        if (entry := hass.config_entries.async_get_entry(entry_id))
        and entry.domain == "esphome"
    ]
    if len(entries) != 1:
        return None
    info = getattr(getattr(entries[0], "runtime_data", None), "device_info", None)
    if info:
        return info.name.replace("-", "_") + "_configure_wake_verifier"
    return None


async def sync_satellites(hass, view):
    """Retry pending devices. A matching response means the URL was saved."""
    try:
        endpoint = get_url(hass, allow_external=False, prefer_external=False).rstrip("/") + PATH
    except NoURLAvailableError:
        return
    for satellite in list(view.satellites.values()):
        entity_id = satellite["satellite_entity_id"]
        if view.paired.get(entity_id) == endpoint:
            continue
        action = node_action(hass, entity_id)
        if not action or not hass.services.has_service("esphome", action):
            continue
        try:
            async with asyncio.timeout(10):
                result = await hass.services.async_call(
                    "esphome", action, {"url": endpoint},
                    blocking=True, return_response=True,
                )
        except (HomeAssistantError, TimeoutError):
            _LOGGER.debug("Wake verifier setup pending for %s", entity_id)
            continue
        if isinstance(result, dict) and result.get("url") == endpoint:
            view.paired[entity_id] = endpoint
            _LOGGER.info("Wake verifier configured for %s", entity_id)
