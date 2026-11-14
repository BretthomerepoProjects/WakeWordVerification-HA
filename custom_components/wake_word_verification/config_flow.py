"""Set up Wake Word Verification from the Home Assistant UI."""
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from . import CONFIG_SCHEMA, DOMAIN


class WakeVerificationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
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
            return await self.async_step_satellite()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("phrase", default="Alexa"): vol.All(str, vol.Length(min=1, max=80)),
                vol.Required("stt_engine"): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="stt")
                ),
                vol.Required("language", default="en-US"): str,
                vol.Required("archive_dir", default="/wake-archive"): str,
            }),
        )

    async def async_step_satellite(self, user_input=None):
        errors = {}
        if user_input is not None:
            entity_id = user_input["satellite_entity_id"]
            state = self.hass.states.get(entity_id)
            candidate = {
                "satellite_entity_id": entity_id,
                "satellite_ip": user_input["satellite_ip"],
                "satellite_name": state.name if state else entity_id,
            }
            satellites = [*self.satellites, candidate]
            try:
                CONFIG_SCHEMA({DOMAIN: {**self.settings, "satellites": satellites}})
            except vol.Invalid:
                errors["base"] = "invalid_satellite"
            else:
                self.satellites = satellites
                if not user_input["add_another"]:
                    return self.async_create_entry(
                        title="Wake Word Verification",
                        data={**self.settings, "satellites": satellites},
                    )
        return self.async_show_form(
            step_id="satellite",
            data_schema=vol.Schema({
                vol.Required("satellite_entity_id"): selector.EntitySelector(
                    selector.EntitySelectorConfig()
                ),
                vol.Required("satellite_ip"): str,
                vol.Required("add_another", default=False): bool,
            }),
            errors=errors,
        )


class SatelliteOptionsFlow(config_entries.OptionsFlow):
    """Add another allowed satellite."""

    async def async_step_init(self, user_input=None):
        current = self.config_entry.options.get(
            "satellites", self.config_entry.data["satellites"]
        )
        errors = {}
        if user_input is not None:
            entity_id = user_input["satellite_entity_id"]
            state = self.hass.states.get(entity_id)
            satellites = [*current, {
                "satellite_entity_id": entity_id,
                "satellite_ip": user_input["satellite_ip"],
                "satellite_name": state.name if state else entity_id,
            }]
            try:
                CONFIG_SCHEMA({DOMAIN: {**self.config_entry.data, "satellites": satellites}})
            except vol.Invalid:
                errors["base"] = "invalid_satellite"
            else:
                return self.async_create_entry(title="", data={"satellites": satellites})
        return self.async_show_form(
            step_id="init",
            description_placeholders={
                "satellites": "\n".join(
                    f"- {entry['satellite_name']} (`{entry['satellite_entity_id']}`) — `{entry['satellite_ip']}`"
                    for entry in current
                )
            },
            data_schema=vol.Schema({
                vol.Required("satellite_entity_id"): selector.EntitySelector(
                    selector.EntitySelectorConfig()
                ),
                vol.Required("satellite_ip"): str,
            }),
            errors=errors,
        )
