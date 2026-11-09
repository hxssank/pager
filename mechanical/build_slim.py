"""Export the USB-C-only packaging target and its provisional battery stack.

Run with uv run python mechanical/build_slim.py.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import cadquery as cq
from geometry import (
    TOLERANCE,
    box,
    dimension_slug,
    gap,
    validate_packing,
    wall_dimensions,
)

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT.parent / "preview" / "dist" / "assets"


def require_equal(actual: float, expected: float, name: str) -> None:
    """Fail when declared stack dimensions drift from the geometry."""
    if (
        not math.isfinite(actual)
        or not math.isfinite(expected)
        or abs(actual - expected) > TOLERANCE
    ):
        raise ValueError(f"Battery stack mismatch for {name}: {actual} vs {expected}")


def validate_layout(layout: dict) -> tuple[dict[str, cq.Workplane], dict]:
    """Check body, battery stack and the single external connector reservation."""
    if layout["units"] != "mm":
        raise ValueError("The packaging contract requires millimetres, units='mm'")
    body = layout["body"]
    walls = wall_dimensions(body)
    parts = {part["id"]: part for part in layout["components"]}
    stack = {part["id"]: part for part in layout["stack_reservations"]}
    battery, display = parts["battery"], parts["display"]
    divider, expansion, interface = (
        stack[name]
        for name in ("battery_divider", "battery_expansion", "battery_interface")
    )
    declared = layout["battery_stack"]
    flags = [
        declared["supplier_approved"],
        declared["thermal_interface_verified"],
        body["rear_thickness_verified"],
        *(part["verified_geometry"] for part in layout["components"]),
        *(part["verified_geometry"] for part in layout["stack_reservations"]),
        *(port["verified_geometry"] for port in layout["external_ports"]),
    ]
    if any(type(flag) is not bool for flag in flags):
        raise ValueError("Verification flags must be booleans")
    if body["rear_material"] != "aluminum":
        raise ValueError("This target requires an aluminum rear material study")
    require_equal(display["position"][2], walls["front"], "display to front wall")
    for axis in (0, 1):
        if (
            divider["position"][axis] < display["position"][axis] - TOLERANCE
            or divider["position"][axis] + divider["size"][axis]
            > display["position"][axis] + display["size"][axis] + TOLERANCE
        ):
            raise ValueError("Battery divider must remain behind the display footprint")
    for part, field in (
        (divider, "divider_mm"),
        (expansion, "expansion_clearance_mm"),
        (interface, "thermal_interface_mm"),
    ):
        require_equal(part["size"][2], declared[field], field)
        for axis in (0, 1):
            require_equal(
                part["position"][axis],
                battery["position"][axis],
                f"{part['id']} position",
            )
            require_equal(
                part["size"][axis], battery["size"][axis], f"{part['id']} size"
            )
    for first, second in (
        (display, divider),
        (divider, expansion),
        (expansion, battery),
        (battery, interface),
    ):
        require_equal(gap(first, second, 2), 0, f"{first['id']} to {second['id']}")
    rear_inner = body["size"][2] - walls["rear"]
    require_equal(
        interface["position"][2] + interface["size"][2], rear_inner, "interface to rear"
    )
    required_expansion = declared["supplier_expansion_required_mm"]
    if required_expansion is not None:
        if not math.isfinite(required_expansion) or required_expansion < 0:
            raise ValueError(
                "Supplier expansion requirement must be finite and nonnegative"
            )
        if declared["expansion_clearance_mm"] + TOLERANCE < required_expansion:
            raise ValueError(
                "Battery expansion reservation is below the supplier requirement"
            )
    if declared["supplier_approved"] and required_expansion is None:
        raise ValueError("Supplier approval requires an explicit expansion requirement")

    ports = layout["external_ports"]
    if len(ports) != 1 or ports[0]["id"] != "usb_c" or ports[0]["edge"] != "top":
        raise ValueError("This target reserves one external USB-C port on the top edge")
    port = ports[0]
    opening = port["opening"]
    connector = {"id": "usb_c_keepout", **port["keepout"]}
    box(opening["position"], opening["size"])
    require_equal(opening["position"][1], 0, "port starts at top edge")
    require_equal(opening["size"][1], walls["side"], "port crosses side wall")
    require_equal(
        connector["position"][1], walls["side"], "connector starts inside top wall"
    )
    for axis in (0, 2):
        if (
            opening["position"][axis] < connector["position"][axis] - TOLERANCE
            or opening["position"][axis] + opening["size"][axis]
            > connector["position"][axis] + connector["size"][axis] + TOLERANCE
        ):
            raise ValueError("USB-C opening must align with its internal keepout")
    reservations = [*layout["components"], *layout["stack_reservations"], connector]
    shapes = validate_packing(body, reservations)
    checks = {
        "status": "Geometric reservation checks only. Pack, thermal contact, connector and enclosure remain unverified.",
        "body_mm": body["size"],
        "wall_mm": walls,
        "all_reservations_inside_rounded_wall": True,
        "component_reservation_intersections": [],
        "display_battery_depth_gap_mm": gap(display, battery, 2),
        "battery_to_outer_rear_mm": round(
            body["size"][2] - battery["position"][2] - battery["size"][2], 6
        ),
        "battery_to_inner_rear_mm": round(
            rear_inner - battery["position"][2] - battery["size"][2], 6
        ),
        "battery_trackball_planar_gap_mm": gap(battery, parts["trackball"], 1),
        "trackball_keyboard_planar_gap_mm": gap(
            parts["trackball"], parts["keyboard"], 1
        ),
        "power_controller_planar_gap_mm": gap(
            parts["power"], parts["display_controller"], 1
        ),
        "battery_stack_mm": {
            key: declared[key]
            for key in ("divider_mm", "expansion_clearance_mm", "thermal_interface_mm")
        },
        "battery_stack_supplier_approved": declared["supplier_approved"],
        "thermal_interface_verified": declared["thermal_interface_verified"],
        "external_connector_ids": [port["id"]],
        "connector_geometry_verified": port["verified_geometry"],
        "manufacturer_display_imported_or_scaled": False,
        "not_checked": layout["unresolved"],
    }
    return shapes, checks


def build(layout: dict, output: Path, assets: Path | None = None) -> dict:
    """Export checked reservations and a grip dummy without deleting prior studies."""
    shapes, checks = validate_layout(layout)
    body = layout["body"]
    walls = wall_dimensions(body)
    slug = dimension_slug(body["size"])
    assembly = cq.Assembly(name=f"slim_{slug}_provisional_target")
    colors = {
        "display": (0.18, 0.24, 0.28),
        "keyboard": (0.22, 0.24, 0.26),
        "battery": (0.72, 0.75, 0.77),
        "power": (0.15, 0.45, 0.31),
        "orange_pi": (0.15, 0.45, 0.31),
        "display_controller": (0.2, 0.38, 0.58),
        "trackball": (0.72, 0.70, 0.62),
        "battery_divider": (0.72, 0.61, 0.42),
        "battery_expansion": (0.85, 0.55, 0.2),
        "battery_interface": (0.3, 0.65, 0.7),
        "usb_c_keepout": (0.45, 0.45, 0.5),
    }
    for name, shape in shapes.items():
        assembly.add(shape, name=f"unverified_{name}", color=cq.Color(*colors[name]))
    rear = (
        box([0, 0, body["size"][2] - walls["rear"]], [*body["size"][:2], walls["rear"]])
        .edges("|Z")
        .fillet(body["corner_radius"])
    )
    assembly.add(
        rear,
        name="provisional_aluminum_rear_pending_RF_window",
        color=cq.Color(0.7, 0.72, 0.75),
    )
    output.mkdir(parents=True, exist_ok=True)
    assembly.export(str(output / "slim-packaging-target.step"))
    dummy = box([0, 0, 0], body["size"]).edges("|Z").fillet(body["corner_radius"])
    for recess in layout["face_recesses"]:
        dummy = dummy.cut(box(recess["position"], recess["size"]))
    for port in layout["external_ports"]:
        opening = port["opening"]
        dummy = dummy.cut(box(opening["position"], opening["size"]))
    if not dummy.val().isValid() or len(dummy.solids().vals()) != 1:
        raise ValueError("The grip dummy must be one valid solid")
    dummy_stem = f"slim-grip-dummy-{slug}"
    for extension in ("step", "stl"):
        cq.exporters.export(dummy, str(output / f"{dummy_stem}.{extension}"))
    checks.update(
        {
            "dummy_valid": dummy.val().isValid(),
            "dummy_solids": len(dummy.solids().vals()),
            "dummy_artifact_stem": dummy_stem,
            "assembly_solid_count": len(shapes) + 1,
        }
    )
    (output / "slim-checks.json").write_text(json.dumps(checks, indent=2) + "\n")
    (output / "slim-layout.json").write_text(json.dumps(layout, indent=2) + "\n")
    if assets is not None:
        assets.mkdir(parents=True, exist_ok=True)
        for filename in (
            "slim-layout.json",
            "slim-checks.json",
            "slim-packaging-target.step",
            f"{dummy_stem}.step",
            f"{dummy_stem}.stl",
        ):
            shutil.copy2(output / filename, assets / filename)
    return checks


def main() -> None:
    """Build the current layout and sync its browser assets."""
    layout = json.loads((ROOT / "slim-layout.json").read_text())
    print(json.dumps(build(layout, ROOT, ASSETS), indent=2))


if __name__ == "__main__":
    main()
