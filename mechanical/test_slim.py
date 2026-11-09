"""Check CAD exports and reject invalid changes to the packaging contract."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import cadquery as cq
import pytest
from build_slim import validate_layout
from geometry import dimension_slug, validate_packing
from OCP.StlAPI import StlAPI_Reader
from OCP.TopoDS import TopoDS_Shape

ROOT = Path(__file__).resolve().parent


@pytest.fixture(scope="module")
def slim_layout() -> dict:
    return json.loads((ROOT / "slim-layout.json").read_text())


@pytest.mark.parametrize("extension", ["step", "stl"])
def test_slim_dummy_export_size(extension: str, slim_layout: dict) -> None:
    path = (
        ROOT
        / f"slim-grip-dummy-{dimension_slug(slim_layout['body']['size'])}.{extension}"
    )
    if extension == "step":
        shape = cq.importers.importStep(str(path)).val()
        assert len(shape.Solids()) == 1
        assert shape.Volume() > 0
    else:
        imported = TopoDS_Shape()
        assert StlAPI_Reader().Read(imported, str(path))
        shape = cq.Shape.cast(imported)
        assert len(shape.Faces()) > 0
    assert shape.isValid()
    bounds = shape.BoundingBox()
    assert [bounds.xlen, bounds.ylen, bounds.zlen] == pytest.approx(
        slim_layout["body"]["size"], abs=1e-4
    )


def test_usb_c_opening_exists_in_export(slim_layout: dict) -> None:
    path = ROOT / f"slim-grip-dummy-{dimension_slug(slim_layout['body']['size'])}.step"
    shape = cq.importers.importStep(str(path)).val()
    opening = slim_layout["external_ports"][0]["opening"]
    probe = cq.Solid.makeBox(*opening["size"], cq.Vector(*opening["position"]))
    assert shape.intersect(probe).Volume() < 1e-6
    assert shape.isInside(cq.Vector(70, 0.7, 12), 1e-6)


def test_export_contains_stack_connector_and_aluminum_rear(slim_layout: dict) -> None:
    shape = cq.importers.importStep(str(ROOT / "slim-packaging-target.step")).val()
    expected = (
        len(slim_layout["components"])
        + len(slim_layout["stack_reservations"])
        + len(slim_layout["external_ports"])
        + 1
    )
    assert len(shape.Solids()) == expected
    bounds = shape.BoundingBox()
    assert [bounds.xmin, bounds.ymin, bounds.zmin] == pytest.approx(
        [0, 0, slim_layout["body"]["wall_mm"]["front"]]
    )
    assert [bounds.xmax, bounds.ymax, bounds.zmax] == pytest.approx(
        slim_layout["body"]["size"]
    )


def test_reports_and_browser_assets_match_source(slim_layout: dict) -> None:
    _, actual = validate_layout(slim_layout)
    saved = json.loads((ROOT / "slim-checks.json").read_text())
    assert all(saved[key] == value for key, value in actual.items())
    assert not any(c["verified_geometry"] for c in slim_layout["components"])
    assert not actual["battery_stack_supplier_approved"]
    assert not actual["thermal_interface_verified"]
    for filename in (
        "slim-layout.json",
        "slim-checks.json",
        "slim-packaging-target.step",
        f"{saved['dummy_artifact_stem']}.step",
        f"{saved['dummy_artifact_stem']}.stl",
    ):
        assert (ROOT / filename).read_bytes() == (
            ROOT.parent / "preview" / "dist" / "assets" / filename
        ).read_bytes()


def test_report_updates_when_valid_geometry_changes(slim_layout: dict) -> None:
    changed = copy.deepcopy(slim_layout)
    keyboard = next(item for item in changed["components"] if item["id"] == "keyboard")
    keyboard["position"][1] -= 0.5
    _, checks = validate_layout(changed)
    assert checks["trackball_keyboard_planar_gap_mm"] == 1.5


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("battery_moves", "stack mismatch"),
        ("rear_too_thick", "stack mismatch"),
        ("divider_wrong", "stack mismatch"),
        ("growth_too_small", "below the supplier requirement"),
        ("approval_without_requirement", "explicit expansion requirement"),
        ("second_port", "one external USB-C"),
        ("misaligned_port", "align with its internal keepout"),
        ("connector_collision", "Intersecting reservations"),
        ("duplicate", "Duplicate reservation"),
    ],
)
def test_rejects_invalid_contract(
    slim_layout: dict, mutation: str, message: str
) -> None:
    changed = copy.deepcopy(slim_layout)
    if mutation == "battery_moves":
        next(c for c in changed["components"] if c["id"] == "battery")["position"][
            2
        ] -= 0.1
    elif mutation == "rear_too_thick":
        changed["body"]["wall_mm"]["rear"] = 1.2
    elif mutation == "divider_wrong":
        changed["battery_stack"]["divider_mm"] = 0.3
    elif mutation == "growth_too_small":
        changed["battery_stack"]["supplier_expansion_required_mm"] = 1.0
    elif mutation == "approval_without_requirement":
        changed["battery_stack"]["supplier_approved"] = True
    elif mutation == "second_port":
        changed["external_ports"].append(copy.deepcopy(changed["external_ports"][0]))
    elif mutation == "misaligned_port":
        changed["external_ports"][0]["opening"]["position"][0] = 60
    elif mutation == "connector_collision":
        changed["external_ports"][0]["keepout"]["size"][1] = 20
    elif mutation == "duplicate":
        changed["components"].append(copy.deepcopy(changed["components"][0]))
    with pytest.raises(ValueError, match=message):
        validate_layout(changed)


@pytest.mark.parametrize(
    "position, size, message",
    [
        ([1.4, 1.4, 2], [1, 1, 1], "rounded interior"),
        ([6, 6, 0.5], [1, 1, 1], "rounded interior"),
        ([6, 6, 16], [1, 1, 1], "rounded interior"),
        ([6, 6, 2], [-1, 1, 1], "positive"),
        ([float("nan"), 6, 2], [1, 1, 1], "finite"),
    ],
)
def test_rejects_wall_corner_and_invalid_volume(
    slim_layout: dict, position: list, size: list, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_packing(
            slim_layout["body"], [{"id": "probe", "position": position, "size": size}]
        )




def test_rejects_wrong_units(slim_layout: dict) -> None:
    changed = copy.deepcopy(slim_layout)
    changed["units"] = "inches"
    with pytest.raises(ValueError, match="millimetres"):
        validate_layout(changed)


@pytest.mark.parametrize("flag", ["supplier_approved", "thermal_interface_verified"])
def test_rejects_string_verification_flags(slim_layout: dict, flag: str) -> None:
    changed = copy.deepcopy(slim_layout)
    changed["battery_stack"][flag] = "false"
    changed["battery_stack"]["supplier_expansion_required_mm"] = 0.8
    with pytest.raises(ValueError, match="booleans"):
        validate_layout(changed)


def test_rejects_disconnected_display_stack(slim_layout: dict) -> None:
    changed = copy.deepcopy(slim_layout)
    display = next(part for part in changed["components"] if part["id"] == "display")
    display["position"][0] = 75
    display["size"][0] = 10
    with pytest.raises(ValueError, match="behind the display footprint"):
        validate_layout(changed)
