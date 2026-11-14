"""Configure the verifier and its permitted satellites."""
import asyncio
from ipaddress import ip_address
import socket

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import stt
from homeassistant.helpers import device_registry, entity_registry, selector

from . import CONFIG_SCHEMA, DOMAIN


async def suggested_ip(hass, entity_id):
    entity = entity_registry.async_get(hass).async_get(entity_id)
    device = device_registry.async_get(hass).async_get(entity.device_id) if entity and entity.device_id else None
    if not device:
        return None
    for entry_id in sorted(device.config_entries):
        entry = hass.config_entries.async_get_entry(entry_id)
        if not entry or entry.domain != "esphome":
            continue
        host = entry.data.get("host")
        if not host:
            continue
        try:
            return str(ip_address(host))
        except ValueError:
            try:
                async with asyncio.timeout(2):
                    answers = await asyncio.get_running_loop().getaddrinfo(
                        host, None, type=socket.SOCK_STREAM
                    )
                addresses = {answer[4][0] for answer in answers}
                if len(addresses) == 1:
                    return addresses.pop()
            except (OSError, TimeoutError):
                pass
    return None


class SetupSteps:
    async def async_step_engine(self, user_input=None):
        errors = {}
        if user_input is not None:
            engine = stt.async_get_speech_to_text_engine(self.hass, user_input["stt_engine"])
            self.languages = sorted(set(engine.supported_languages)) if engine else []
            if self.languages:
                self.settings.update(user_input)
                return await self.async_step_language()
            errors["base"] = "stt_unavailable"
        return self.async_show_form(
            step_id="engine", errors=errors,
            data_schema=vol.Schema({
                vol.Required("stt_engine", description={
                    "suggested_value": self.settings.get("stt_engine")
                }): selector.EntitySelector(selector.EntitySelectorConfig(domain="stt")),
            }),
        )

    async def async_step_language(self, user_input=None):
        if user_input is not None and user_input["language"] in self.languages:
            self.settings.update(user_input)
            return await self.stt_configured()
        current = self.settings.get("language")
        preferred = current if current in self.languages else next(
            (language for language in ("en", "en-US") if language in self.languages),
            self.languages[0],
        )
        return self.async_show_form(
            step_id="language",
            errors={"base": "invalid_language"} if user_input is not None else {},
            data_schema=vol.Schema({
                vol.Required("language", default=preferred): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=self.languages)
                ),
            }),
        )

    async def async_step_satellite(self, user_input=None):
        if user_input is not None:
            self.entity_id = user_input["satellite_entity_id"]
            self.address = await suggested_ip(self.hass, self.entity_id)
            return await self.async_step_address()
        return self.async_show_form(
            step_id="satellite", data_schema=vol.Schema({
                vol.Required("satellite_entity_id"): selector.EntitySelector(
                    selector.EntitySelectorConfig()
                ),
            }),
        )

    async def async_step_address(self, user_input=None):
        errors = {}
        if user_input is not None:
            self.address = user_input["satellite_ip"]
            state = self.hass.states.get(self.entity_id)
            satellites = [*self.satellites, {
                "satellite_entity_id": self.entity_id,
                "satellite_ip": self.address,
                "satellite_name": state.name if state else self.entity_id,
            }]
            try:
                CONFIG_SCHEMA({DOMAIN: {**self.settings, "satellites": satellites}})
            except vol.Invalid:
                errors["base"] = "invalid_satellite"
            else:
                self.satellites = satellites
                if user_input["add_another"]:
                    return await self.async_step_satellite()
                return self.finish()
        return self.async_show_form(
            step_id="address", errors=errors, data_schema=vol.Schema({
                vol.Required("satellite_ip", description={"suggested_value": self.address or ""}): str,
                vol.Required("add_another", default=False): bool,
            }),
        )


class WakeVerificationConfigFlow(SetupSteps, config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.settings = {}
        self.satellites = []

    @staticmethod
    def async_get_options_flow(config_entry):
        return SatelliteOptionsFlow()

    async def async_step_user(self, user_input=None):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            self.settings = user_input
            return await self.async_step_engine()
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema({
                vol.Required("phrase", default="Alexa"): vol.All(str, vol.Length(min=1, max=80)),
                vol.Optional("archive_dir", default=""): str,
            }),
        )

    async def stt_configured(self):
        return await self.async_step_satellite()

    def finish(self):
        return self.async_create_entry(
            title="Wake Word Verification", data={**self.settings, "satellites": self.satellites}
        )


class SatelliteOptionsFlow(SetupSteps, config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        self.settings = {**self.config_entry.data, **self.config_entry.options}
        self.satellites = self.settings.pop("satellites")
        paired = getattr(self.hass.data.get(DOMAIN), "paired", {})
        return self.async_show_menu(
            step_id="init", menu_options=["satellite", "engine"] + (["remove_satellite"] if self.satellites else []),
            description_placeholders={"satellites": "\n".join(
                f"- {entry['satellite_name']} (`{entry['satellite_entity_id']}`) — `{entry['satellite_ip']}`"
                + (" · Ready" if entry["satellite_entity_id"] in paired else " · Pending")
                for entry in self.satellites
            )},
        )

    async def stt_configured(self):
        return self.finish()

    def finish(self):
        return self.async_create_entry(title="", data={**self.settings, "satellites": self.satellites})


    async def async_step_remove_satellite(self, user_input=None):
        if user_input is not None:
            entity_id = user_input["satellite_entity_id"]
            self.satellites = [
                entry for entry in self.satellites
                if entry["satellite_entity_id"] != entity_id
            ]
            return self.finish()
        return self.async_show_form(
            step_id="remove_satellite",
            data_schema=vol.Schema({
                vol.Required("satellite_entity_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        {"value": entry["satellite_entity_id"],
                         "label": f"{entry['satellite_name']} ({entry['satellite_ip']})"}
                        for entry in self.satellites
                    ])
                ),
            }),
        )
