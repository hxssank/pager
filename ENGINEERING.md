# A thickness budget that can reject its own design

Pager's slim model is a packaging calculation expressed as CAD. Its useful result is not simply a 17.4 mm render. It is a set of constraints that can reject that thickness when the display, battery stack or connectors stop fitting.

This document traces the self-contained public slim model. The tradeoff explanations are inferred from its geometry and declared constraints. The dimensions are design reservations, not measurements of a finished handheld.

## Trace the geometry contract

[`slim-layout.json`](mechanical/slim-layout.json) declares millimetres, the coordinate axes, outer dimensions, wall thicknesses, component boxes, battery-stack reservations and the USB-C opening. Positions are the minimum corner of each axis-aligned box. The `verified_geometry` fields remain false; a valid box is not evidence that a matching component exists.

[`build_slim.main()`](mechanical/build_slim.py) loads that contract and calls `build()`. Before exporting anything, `build()` calls `validate_layout()`. That function checks units, boolean verification flags, the declared aluminum rear, the display's front-wall offset, battery-stack adjacency and connector alignment.

It then passes the component, stack and connector reservations to [`validate_packing()`](mechanical/geometry.py). `packing_shapes()` rejects duplicate IDs instead of letting one dictionary entry silently overwrite another. `rounded_interior()` subtracts the front, side and rear walls and fillets the usable volume. Each reservation is cut against that interior; any remaining volume above the numerical threshold means it crosses the usable boundary. Pairwise solid intersections detect overlaps.

```mermaid
flowchart LR
    Layout[Millimetre layout and evidence flags] --> Stack[Stack and connector constraints]
    Stack --> Volume[Rounded enclosure containment]
    Volume --> Collisions[Pairwise intersection checks]
    Collisions --> CAD[Assembly STEP and grip dummy]
    CAD --> Report[Dimensions and unresolved checks]
```

Only after validation does `build()` create the assembly and cut the display, keyboard, trackball and USB-C recesses into the dummy. It requires the dummy to remain one valid solid. `dimension_slug()` derives its filename from the declared dimensions, so the export's name cannot silently keep an obsolete thickness.

## Where 17.4 mm goes

The display and battery overlap in plan, so their depths add. The contract assigns this front-to-back stack:

| Layer | Thickness | End position from the front |
| --- | ---: | ---: |
| Front wall | 1.4 mm | 1.4 mm |
| Display assembly reservation | 6.8 mm | 8.2 mm |
| Protective divider | 0.2 mm | 8.4 mm |
| Forward battery expansion space | 0.8 mm | 9.2 mm |
| Protected battery reservation | 7.0 mm | 16.2 mm |
| Insulating thermal interface | 0.2 mm | 16.4 mm |
| Aluminum rear | 1.0 mm | 17.4 mm |

The sum is exactly 17.4 mm. `require_equal()` and `gap()` check those adjacent boundaries. The 1.0 mm display-to-battery gap is already occupied by the 0.2 mm divider and 0.8 mm expansion reservation. It is not another millimetre available for a cable.

This exposes the main dependency: the display is a hypothetical 6.8 mm assembly. Substituting the referenced 14.04 mm stock assembly adds 7.24 mm and makes the same stack 24.64 mm thick before any further changes. That is arithmetic from the stored dimensions, not a revised enclosure design. Scaling the stock mesh until it fits would erase the problem instead of solving it.

Tolerance also consumes space. As an illustrative scenario, an extra 0.2 mm of display height, 0.3 mm of protected-pack height and 0.1 mm of rear thickness raises the stack to 18.0 mm. Those additions are assumptions, not supplier tolerances. The current nominal stack has no spare depth to absorb them.

## Tradeoffs made visible

**Bounding boxes make early rejection cheap, but omit detail.** They make the contract readable and let a changed dimension rerun the same checks. A detailed manufacturer solid could expose connector overhangs or provide a less conservative shape. Neither representation supplies a missing cable bend, strain relief or screw boss automatically. The current boxes must not become substitutes for controlled component drawings.

**The rounded interior catches a failure that rectangular limits miss.** A small box can have every coordinate between the side-wall limits yet protrude into a corner fillet. Boolean containment catches that case. It costs more computation than comparing minimum and maximum coordinates, but uses the actual reserved interior shape. `TOLERANCE = 1e-6` is a numerical threshold applied to CAD volume checks; it is not a manufacturing tolerance of one micrometre.

**A thin aluminum rear changes the thermal and radio problem.** The model explicitly requires aluminum for the 1.0 mm rear study. Replacing it with equally thin printed plastic would preserve dimensions while changing stiffness. A metal rear can also spread computer heat toward the battery and obstruct an antenna. Geometry validation does not evaluate either effect. A thicker polymer rear or different component arrangement changes the thickness budget and needs a new contract.

**A single external opening does not remove internal sockets.** The USB-C keepout includes provisional connector space, while the computer's 7 mm populated reservation retains its sockets. Touch, keyboard and HDMI connections still need physical paths inside. Removing a connector from the visible exterior is not a reduction in its volume or in the clearance needed to mate it.

## Invariants, evidence and the next decision

[`test_slim.py`](mechanical/test_slim.py) checks exported dimensions, solid validity, the USB-C cutout and agreement between reports and generated assets. Negative cases include wrong units, malformed verification flags, intersections and rounded-wall violations. These tests establish that the generator follows its contract. They cannot establish that the contract describes purchasable parts, a comfortable keyboard or an acceptable battery installation.

A proposed next gate is to obtain controlled drawings for the exact display/controller and protected pack, including connectors and supplier-required expansion clearance. Enter maximum specified dimensions rather than nominal catalogue dimensions. Pass only if the updated reservations fit, the required expansion space fits without pouch compression, and all connector paths can be represented without collisions. If the display exceeds 6.8 mm, the protected pack exceeds 7.0 mm, or required expansion exceeds 0.8 mm, the current stack fails unless another documented dimension changes. The next action is to revise the envelope, not silently shrink a component model.
