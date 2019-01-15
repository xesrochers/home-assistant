"""Translation string lookup helpers."""
import logging
import pathlib
from typing import Any, Dict, Iterable

from homeassistant import config_entries
from homeassistant.loader import get_component, get_platform, bind_hass
from homeassistant.util.json import load_json
from .typing import HomeAssistantType

_LOGGER = logging.getLogger(__name__)

TRANSLATION_STRING_CACHE = 'translation_string_cache'


def recursive_flatten(prefix: Any, data: Dict) -> Dict[str, Any]:
    """Return a flattened representation of dict data."""
    output = {}
    for key, value in data.items():
        if isinstance(value, dict):
            output.update(
                recursive_flatten('{}{}.'.format(prefix, key), value))
        else:
            output['{}{}'.format(prefix, key)] = value
    return output


def flatten(data: Dict) -> Dict[str, Any]:
    """Return a flattened representation of dict data."""
    return recursive_flatten('', data)


def component_translation_file(hass: HomeAssistantType, component: str,
                               language: str) -> str:
    """Return the translation json file location for a component.

    For component: light/.translations/nl.json
    For platform one of:
     - light/.translations/hue.nl.json
     - hue/.translations/light.nl.json
    """
    is_platform = '.' in component

    if not is_platform:
        module = get_component(hass, component)
        assert module is not None

        module_path = pathlib.Path(module.__file__)

        if module.__name__ == module.__package__:
            # light/__init__.py
            filename = '{}.json'.format(language)
        else:
            # group.py
            filename = '{}.{}.json'.format(component, language)

        return module_path.parent / '.translations' / filename

    # It's a platform
    parts = component.split('.', 1)
    module = get_platform(hass, *parts)
    assert module is not None

    # Either within HA or custom_components
    # Either light/hue.py or hue/light.py
    module_path = pathlib.Path(module.__file__)

    # Compare to parent so we don't have to strip off `.py`
    if module_path.parent.name == parts[0]:
        # this is light/hue.py
        filename = "{}.{}.json".format(parts[1], language)
    else:
        # this is hue/light.py
        filename = "{}.{}.json".format(parts[0], language)

    return module_path.parent / '.translations' / filename


def load_translations_files(translation_files: Dict[str, str]) \
        -> Dict[str, Dict[str, Any]]:
    """Load and parse translation.json files."""
    loaded = {}
    for component, translation_file in translation_files.items():
        loaded_json = load_json(translation_file)
        assert isinstance(loaded_json, dict)
        loaded[component] = loaded_json

    return loaded


def build_resources(translation_cache: Dict[str, Dict[str, Any]],
                    components: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """Build the resources response for the given components."""
    # Build response
    resources = {}  # type: Dict[str, Dict[str, Any]]
    for component in components:
        if '.' not in component:
            domain = component
        else:
            domain = component.split('.', 1)[0]

        if domain not in resources:
            resources[domain] = {}

        # Add the translations for this component to the domain resources.
        # Since clients cannot determine which platform an entity belongs to,
        # all translations for a domain will be returned together.
        resources[domain].update(translation_cache[component])

    return resources


@bind_hass
async def async_get_component_resources(hass: HomeAssistantType,
                                        language: str) -> Dict[str, Any]:
    """Return translation resources for all components."""
    if TRANSLATION_STRING_CACHE not in hass.data:
        hass.data[TRANSLATION_STRING_CACHE] = {}
    if language not in hass.data[TRANSLATION_STRING_CACHE]:
        hass.data[TRANSLATION_STRING_CACHE][language] = {}
    translation_cache = hass.data[TRANSLATION_STRING_CACHE][language]

    # Get the set of components
    components = hass.config.components | set(config_entries.FLOWS)

    # Calculate the missing components
    missing_components = components - set(translation_cache)
    missing_files = {}
    for component in missing_components:
        missing_files[component] = component_translation_file(
            hass, component, language)

    # Load missing files
    if missing_files:
        load_translations_job = hass.async_add_job(
            load_translations_files, missing_files)
        assert load_translations_job is not None
        loaded_translations = await load_translations_job

        # Update cache
        translation_cache.update(loaded_translations)

    resources = build_resources(translation_cache, components)

    # Return the component translations resources under the 'component'
    # translation namespace
    return flatten({'component': resources})


@bind_hass
async def async_get_translations(hass: HomeAssistantType,
                                 language: str) -> Dict[str, Any]:
    """Return all backend translations."""
    resources = await async_get_component_resources(hass, language)
    if language != 'en':
        # Fetch the English resources, as a fallback for missing keys
        base_resources = await async_get_component_resources(hass, 'en')
        resources = {**base_resources, **resources}

    return resources
