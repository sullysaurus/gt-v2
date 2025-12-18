"""OpenAI Vision service for analyzing seatmap images."""
import base64
import json
from pathlib import Path
from typing import Optional

from openai import OpenAI

from app.config import OPENAI_API_KEY


SEATMAP_ANALYSIS_PROMPT = """Analyze this stadium/arena seatmap image and extract structured information.

Return a JSON object with the following structure:
{
  "venue_type": "baseball" | "hockey" | "basketball" | "football" | "concert" | "other",
  "venue_shape": "horseshoe" | "oval" | "rectangle" | "circular" | "other",
  "estimated_capacity": number (rough estimate),
  "tiers": [
    {
      "level": 100 | 200 | 300 | 400,
      "name": "Lower Level" | "Club Level" | "Upper Deck" | etc,
      "relative_elevation": "low" | "medium" | "high" | "very_high"
    }
  ],
  "sections": [
    {
      "id": "section number/name as shown",
      "tier": 100 | 200 | 300 | 400,
      "position": "behind_home" | "first_base" | "third_base" | "outfield" | "center" | "corner" | "end",
      "approximate_polygon": [[x1, y1], [x2, y2], [x3, y3], [x4, y4]],
      "angle_from_center": number (-180 to 180, where 0 is behind home plate/center)
    }
  ],
  "field_center": {
    "x": number (0-1 normalized),
    "y": number (0-1 normalized)
  },
  "notes": "any relevant observations about the layout"
}

For the polygon coordinates:
- Use normalized coordinates from 0 to 1 (0,0 is top-left, 1,1 is bottom-right)
- Define 4 corner points for each section in clockwise order
- Be as accurate as possible based on the visible section boundaries

For angles:
- 0 degrees = directly behind home plate (baseball) or center ice/court
- Positive angles = clockwise (toward first base / right side)
- Negative angles = counter-clockwise (toward third base / left side)

Focus on the main seating sections. You don't need to identify every single section -
focus on getting accurate polygons for representative sections in each tier and position.
Aim to identify 15-30 key sections across different areas of the venue."""


class SeatmapAnalyzer:
    """Analyzes seatmap images using OpenAI Vision."""

    def __init__(self, api_key: Optional[str] = None):
        self.client = OpenAI(api_key=api_key or OPENAI_API_KEY)

    def _encode_image(self, image_path: Path) -> str:
        """Encode image to base64 for API."""
        with open(image_path, "rb") as f:
            return base64.standard_b64encode(f.read()).decode("utf-8")

    def _get_mime_type(self, image_path: Path) -> str:
        """Get MIME type from file extension."""
        suffix = image_path.suffix.lower()
        mime_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        return mime_types.get(suffix, "image/png")

    def analyze(self, image_path: Path) -> dict:
        """
        Analyze a seatmap image and extract section information.

        Args:
            image_path: Path to the seatmap image

        Returns:
            Dictionary with venue analysis results
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        # Encode image
        base64_image = self._encode_image(image_path)
        mime_type = self._get_mime_type(image_path)

        # Call OpenAI Vision
        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that analyzes stadium seatmaps. Always respond with valid JSON only, no markdown formatting."
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": SEATMAP_ANALYSIS_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{base64_image}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            max_tokens=4096,
        )

        # Parse response - handle potential markdown code blocks
        content = response.choices[0].message.content
        # Strip markdown code block if present
        if content.startswith("```"):
            lines = content.split("\n")
            # Remove first and last lines (```json and ```)
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return json.loads(content)

    def generate_venue_config(
        self,
        image_path: Path,
        venue_id: str,
        venue_name: str,
        template_name: Optional[str] = None
    ) -> dict:
        """
        Generate a complete venue configuration from seatmap analysis.

        Args:
            image_path: Path to seatmap image
            venue_id: Unique identifier for the venue
            venue_name: Display name for the venue
            template_name: Blender template file name (auto-detected if not provided)

        Returns:
            Complete venue configuration dictionary
        """
        from PIL import Image

        # Get image dimensions
        with Image.open(image_path) as img:
            width, height = img.size

        # Analyze the seatmap
        analysis = self.analyze(image_path)

        # Map venue type to template
        if template_name is None:
            template_map = {
                "baseball": "baseball_stadium.blend",
                "hockey": "hockey_arena.blend",
                "basketball": "basketball_arena.blend",
                "football": "football_stadium.blend",
                "concert": "concert_venue.blend",
            }
            template_name = template_map.get(
                analysis.get("venue_type", "other"),
                "generic_venue.blend"
            )

        # Build tier configuration
        tier_configs = {}
        elevation_map = {
            "low": 5.0,
            "medium": 15.0,
            "high": 28.0,
            "very_high": 40.0,
        }
        distance_map = {
            "low": (25, 50),
            "medium": (45, 70),
            "high": (60, 85),
            "very_high": (75, 100),
        }

        for tier in analysis.get("tiers", []):
            level = tier.get("level", 100)
            elevation = tier.get("relative_elevation", "low")
            tier_configs[level] = {
                "elevation": elevation_map.get(elevation, 10.0),
                "distance_range": list(distance_map.get(elevation, (30, 60))),
            }

        # Build section configurations
        sections = []
        for section in analysis.get("sections", []):
            sections.append({
                "id": str(section.get("id", "")),
                "tier": section.get("tier", 100),
                "polygon": section.get("approximate_polygon", []),
                "angle": section.get("angle_from_center", 0),
            })

        # Build complete config
        config = {
            "venue": {
                "id": venue_id,
                "name": venue_name,
                "type": analysis.get("venue_type", "other"),
                "template": template_name,
                "seatmap": {
                    "file": "seatmap.png",
                    "width": width,
                    "height": height,
                },
                "field_center": {
                    "x": analysis.get("field_center", {}).get("x", 0.5) * 100 - 50,  # Convert to meters
                    "y": analysis.get("field_center", {}).get("y", 0.5) * 100 - 50,
                    "z": 0,
                },
                "tiers": tier_configs,
                "sections": sections,
            }
        }

        return config
