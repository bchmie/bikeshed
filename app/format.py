from __future__ import annotations

from app.models import Part


def num(value) -> str:
    """Human display of a number: 3100.0 -> '3,100', 0.75 -> '0.75'."""
    if value is None:
        return ""
    number = float(value)
    if number == int(number):
        return f"{int(number):,}"
    return f"{number:g}"


def numinput(value) -> str:
    """Value for an <input type=number>: 3100.0 -> '3100', 0.75 -> '0.75'."""
    if value is None:
        return ""
    number = float(value)
    if number == int(number):
        return str(int(number))
    return f"{number:g}"


def km(value) -> str:
    if value is None:
        return "—"
    return f"{float(value):,.0f} km"


def wear_label(part: Part) -> str:
    if part.threshold is None:
        return part.wear_unit
    value = numinput(part.threshold)
    if part.wear_unit == "km":
        return f"{value} km"
    if part.wear_unit == "days":
        return f"{value} days"
    if part.wear_unit == "uses":
        return f"{value} uses"
    if part.wear_unit == "wet_rides":
        return f"{value} wet rides"
    return f"{value} {part.wear_unit}"
