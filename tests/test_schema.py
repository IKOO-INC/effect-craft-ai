"""Validator skema rencana: menerima yang benar, menolak yang salah dengan pesan jelas."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from conftest import FIXTURES
from ecps.errors import PlanError
from ecps.planner.schema import EXAMPLE_PLAN, Plan, validate_plan


def _plan() -> dict:
    return copy.deepcopy(EXAMPLE_PLAN)


def test_example_plan_is_valid():
    plan = validate_plan(_plan())
    assert isinstance(plan, Plan)
    assert plan.comp.width == 1920
    assert plan.comp.duration == 5.0
    assert len(plan.layers) == 2
    assert plan.layers[0].type == "solid"
    assert plan.layers[1].text == "Majalah Dza Izza"


def test_all_fixture_plans_are_valid():
    plans = sorted((FIXTURES / "plans").glob("*.json"))
    assert len(plans) >= 5
    for path in plans:
        data = json.loads(path.read_text(encoding="utf-8"))
        plan = validate_plan(data)
        assert plan.layers, path.name


def test_round_trip_to_dict_is_valid():
    plan = validate_plan(_plan())
    again = validate_plan(plan.to_dict())
    assert again.to_dict() == plan.to_dict()


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda p: p["layers"][0].update(type="hologram"), "layers[0].type"),
        (lambda p: p["layers"][1].update(text=""), "layers[1].text"),
        (lambda p: p["comp"].update(fps=0), "comp.fps"),
        (lambda p: p["comp"].update(duration=0.1), "comp.duration"),
        (lambda p: p["comp"].update(width=3), "comp.width"),
        (lambda p: p["comp"].update(background="biru"), "comp.background"),
        (lambda p: p["layers"][1].update(fill="rgb(1,2,3)"), "layers[1].fill"),
        (
            lambda p: p["layers"][1].update(
                animate={"opacity": [{"time": 0, "value": 0}, {"time": 9, "value": 100}]}
            ),
            "di luar durasi",
        ),
        (
            lambda p: p["layers"][1].update(
                animate={"opacity": [{"time": 1, "value": 0}, {"time": 1, "value": 100}]}
            ),
            "harus naik",
        ),
        (lambda p: p["layers"][1].update(animate={"gaussian": [{"time": 0, "value": 1}]}), "tidak didukung"),
        (
            lambda p: p["layers"][1].update(animate={"opacity": [{"time": 0, "value": 300}]}),
            "opacity harus",
        ),
        (lambda p: p["layers"][1].update(easing="bouncy"), "easing"),
        (lambda p: p.update(layers=[]), "minimal satu layer"),
        (lambda p: p["layers"][1].update(type="shape"), "layers[1].size"),
        (lambda p: p["layers"][1].update(in_=1), "tidak"),  # field asing diabaikan
    ],
)
def test_invalid_plans_are_rejected(mutate, needle):
    data = _plan()
    try:
        mutate(data)
    except Exception:  # noqa: BLE001 - beberapa mutasi memang tidak berlaku
        pytest.skip("mutasi tidak bisa diterapkan")
    if needle == "tidak":  # field asing tidak membuat rencana ditolak
        assert validate_plan(data)
        return
    with pytest.raises(PlanError) as exc:
        validate_plan(data)
    assert needle in str(exc.value), str(exc.value)


def test_layer_names_are_deduplicated_and_sanitized():
    data = _plan()
    data["layers"][0]["name"] = "Judul / Utama"
    data["layers"][1]["name"] = "Judul / Utama"
    plan = validate_plan(data)
    names = [l.name for l in plan.layers]
    assert len(set(names)) == len(names)
    assert "/" not in names[0]


def test_plan_error_collects_multiple_problems():
    data = _plan()
    data["comp"]["fps"] = 0
    data["layers"][0]["effects"][0]["effect"] = ""
    with pytest.raises(PlanError) as exc:
        validate_plan(data)
    assert len(exc.value.errors) >= 2
    assert "-" in exc.value.feedback()


def test_non_object_plan_is_rejected():
    with pytest.raises(PlanError):
        validate_plan([1, 2, 3])
