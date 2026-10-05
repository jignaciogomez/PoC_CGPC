"""Load deployment definitions without silently accepting duplicate YAML keys."""

from pathlib import Path
import yaml


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in result:
            raise ValueError(f"Duplicate YAML key {key!r} at line {key_node.start_mark.line + 1}")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def load_yaml(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        document = yaml.load(handle, Loader=UniqueKeyLoader)
    if not isinstance(document, dict):
        raise ValueError(f"{path}: YAML root must be a mapping")
    return document
