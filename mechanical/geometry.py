"""Shared validation for axis-aligned packaging reservations."""

from __future__ import annotations

import math
from itertools import combinations

import cadquery as cq

TOLERANCE = 1e-6


def box(position: list[float], size: list[float]) -> cq.Workplane:
    """Build a reservation in millimetres."""
    if len(position) != 3 or len(size) != 3:
        raise ValueError("Reservation position and size must have three coordinates")
    if not all(math.isfinite(value) for value in [*position, *size]):
        raise ValueError("Reservation coordinates must be finite")
    if any(value <= 0 for value in size):
        raise ValueError("Reservation dimensions must be positive")
    return cq.Workplane("XY").box(*size, centered=False).translate(position)


def wall_dimensions(body: dict) -> dict[str, float]:
    """Read separate walls or the original stock study's uniform wall."""
    walls = body.get("wall_mm")
    if walls is None:
        walls = dict.fromkeys(["front", "side", "rear"], body["minimum_wall_reserved"])
    if any(
        not math.isfinite(walls[key]) or walls[key] <= 0
        for key in ("front", "side", "rear")
    ):
        raise ValueError("Wall thicknesses must be finite and positive")
    return walls


def rounded_interior(body: dict) -> cq.Shape:
    """Build the usable volume with the actual front and rear wall offsets."""
    walls = wall_dimensions(body)
    width, height, depth = body["size"]
    side = walls["side"]
    radius = body["corner_radius"]
    if not math.isfinite(radius) or radius <= side or radius >= min(width, height) / 2:
        raise ValueError(
            "Corner radius must fit between the side wall and body half-width"
        )
    return (
        box(
            [side, side, walls["front"]],
            [
                width - 2 * side,
                height - 2 * side,
                depth - walls["front"] - walls["rear"],
            ],
        )
        .edges("|Z")
        .fillet(radius - side)
        .val()
    )


def packing_shapes(reservations: list[dict]) -> dict[str, cq.Workplane]:
    """Reject duplicate IDs instead of silently replacing a volume."""
    result = {}
    for item in reservations:
        name = item["id"]
        if name in result:
            raise ValueError(f"Duplicate reservation ID: {name}")
        result[name] = box(item["position"], item["size"])
    return result


def validate_packing(body: dict, reservations: list[dict]) -> dict[str, cq.Workplane]:
    """Reject collisions and reservations outside the rounded inner walls."""
    shapes = packing_shapes(reservations)
    interior = rounded_interior(body)
    for name, shape in shapes.items():
        if shape.val().cut(interior).Volume() > TOLERANCE:
            raise ValueError(f"Reservation does not fit the rounded interior: {name}")
    for (first_name, first), (second_name, second) in combinations(shapes.items(), 2):
        if first.val().intersect(second.val()).Volume() > TOLERANCE:
            raise ValueError(f"Intersecting reservations: {first_name}, {second_name}")
    return shapes


def gap(first: dict, second: dict, axis: int) -> float:
    """Return signed separation from the first volume's end to the second start."""
    return round(
        second["position"][axis] - first["position"][axis] - first["size"][axis], 6
    )


def dimension_slug(size: list[float]) -> str:
    """Keep artifact names tied to the dimensions that generated them."""
    return "x".join(f"{value:g}" for value in size)
