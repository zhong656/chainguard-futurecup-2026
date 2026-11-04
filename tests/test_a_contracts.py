"""A-owned contract decisions that the generic good/bad examples cannot cover."""

import copy
import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]


def load_json(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def test_llm_response_mock_flag_matches_actual_provider() -> None:
    schema = load_json("contracts/llm_response.schema.json")
    response = load_json("contracts/examples/llm_response.good.json")
    validator = Draft202012Validator(schema)
    assert validator.is_valid(response)
    assert response["usage"] == {"tokens_in": 0, "tokens_out": 0}

    response["mock"] = False
    assert not validator.is_valid(response)

    response["mock"] = True
    response["usage"]["tokens_in"] = 1
    assert not validator.is_valid(response)

    response["provider"] = "deepseek"
    response["mock"] = False
    assert validator.is_valid(response)

    response.pop("degraded")
    assert not validator.is_valid(response)


def test_task_state_requires_call_limit_and_complete_checkpoint() -> None:
    schema = load_json("contracts/task_state.schema.json")
    state = load_json("contracts/examples/task_state.good.json")
    validator = Draft202012Validator(schema)
    assert validator.is_valid(state)

    no_limit = copy.deepcopy(state)
    no_limit["budget"].pop("calls_max")
    assert not validator.is_valid(no_limit)

    no_checkpoint_path = copy.deepcopy(state)
    no_checkpoint_path["checkpoint"].pop("path")
    assert not validator.is_valid(no_checkpoint_path)


def test_llm_config_supports_mock_and_only_contract_providers() -> None:
    config = yaml.safe_load((ROOT / "configs/llm.yaml").read_text(encoding="utf-8"))
    schema = load_json("contracts/llm_response.schema.json")
    providers = set(schema["properties"]["provider"]["enum"])

    assert isinstance(config, dict)
    assert config["provider"] == "mock"
    assert set(config["providers"]) == providers
    assert set(config["providers"]["mock"]) == {"small", "strong"}
    assert all(config["providers"]["mock"].values())
    assert set(config["routing"].values()) <= set(config["tiers"])
    assert all(set(chain) <= providers for chain in config["fallback"].values())
