"""Geometry utilities for coordinate mapping."""
import math
from typing import Optional


def point_in_polygon(x: float, y: float, polygon: list[list[float]]) -> bool:
    """
    Check if a point is inside a polygon using ray casting algorithm.

    Args:
        x: X coordinate of the point
        y: Y coordinate of the point
        polygon: List of [x, y] vertices defining the polygon

    Returns:
        True if point is inside polygon, False otherwise
    """
    n = len(polygon)
    inside = False

    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]

        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i

    return inside


def polygon_centroid(polygon: list[list[float]]) -> tuple[float, float]:
    """
    Calculate the centroid of a polygon.

    Args:
        polygon: List of [x, y] vertices

    Returns:
        Tuple of (x, y) centroid coordinates
    """
    n = len(polygon)
    if n == 0:
        return (0, 0)

    cx = sum(p[0] for p in polygon) / n
    cy = sum(p[1] for p in polygon) / n
    return (cx, cy)


def distance_to_polygon_edge(
    x: float, y: float, polygon: list[list[float]]
) -> tuple[float, float]:
    """
    Calculate the minimum distance from a point to the polygon edges
    and the normalized position (0 = at front edge, 1 = at back edge).

    This is used to estimate row position within a section.

    Returns:
        Tuple of (min_distance_to_edge, normalized_depth)
    """
    n = len(polygon)
    if n < 3:
        return (0, 0.5)

    # Find the centroid to use as reference
    cx, cy = polygon_centroid(polygon)

    # Calculate distances to all edges
    min_dist = float('inf')

    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]

        # Point to line segment distance
        dx = x2 - x1
        dy = y2 - y1
        length_sq = dx*dx + dy*dy

        if length_sq == 0:
            dist = math.sqrt((x - x1)**2 + (y - y1)**2)
        else:
            t = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / length_sq))
            proj_x = x1 + t * dx
            proj_y = y1 + t * dy
            dist = math.sqrt((x - proj_x)**2 + (y - proj_y)**2)

        min_dist = min(min_dist, dist)

    # Calculate normalized depth (distance from centroid / max possible distance)
    dist_from_center = math.sqrt((x - cx)**2 + (y - cy)**2)

    # Estimate max radius of polygon
    max_radius = max(
        math.sqrt((p[0] - cx)**2 + (p[1] - cy)**2)
        for p in polygon
    )

    normalized_depth = dist_from_center / max_radius if max_radius > 0 else 0.5

    return (min_dist, min(1.0, normalized_depth))


def calculate_angle_from_center(
    x: float, y: float,
    center_x: float = 0.5,
    center_y: float = 0.5
) -> float:
    """
    Calculate angle in degrees from center point.
    0 degrees = directly below center (home plate direction for baseball)
    90 degrees = to the right

    Args:
        x, y: Point coordinates (normalized 0-1)
        center_x, center_y: Center point coordinates

    Returns:
        Angle in degrees (-180 to 180)
    """
    dx = x - center_x
    dy = y - center_y

    # atan2 returns angle from positive X axis, convert to our convention
    angle_rad = math.atan2(dx, -dy)  # -dy because Y increases downward in image
    angle_deg = math.degrees(angle_rad)

    return angle_deg


def interpolate_position(
    t: float,
    start: tuple[float, float, float],
    end: tuple[float, float, float]
) -> tuple[float, float, float]:
    """
    Linear interpolation between two 3D points.

    Args:
        t: Interpolation factor (0 = start, 1 = end)
        start: Starting point (x, y, z)
        end: Ending point (x, y, z)

    Returns:
        Interpolated point (x, y, z)
    """
    return (
        start[0] + t * (end[0] - start[0]),
        start[1] + t * (end[1] - start[1]),
        start[2] + t * (end[2] - start[2])
    )
