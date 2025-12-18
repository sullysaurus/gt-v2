"""Flux depth estimation service for venue setup."""
import base64
from pathlib import Path
from typing import Optional
import io

import replicate
from PIL import Image

from app.config import REPLICATE_API_TOKEN


class DepthEstimator:
    """Estimates depth from seatmap images using Flux on Replicate."""

    def __init__(self, api_token: Optional[str] = None):
        if api_token or REPLICATE_API_TOKEN:
            # Set the token for replicate
            import os
            os.environ["REPLICATE_API_TOKEN"] = api_token or REPLICATE_API_TOKEN

    def estimate_depth(self, image_path: Path) -> Image.Image:
        """
        Generate a depth map from a seatmap image.

        This helps calibrate tier elevations by showing relative
        "depth" (which in top-down seatmaps corresponds to height).

        Args:
            image_path: Path to the seatmap image

        Returns:
            PIL Image containing the depth map
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        # Read and encode the image
        with open(image_path, "rb") as f:
            image_data = f.read()

        # Convert to base64 data URI
        base64_image = base64.b64encode(image_data).decode("utf-8")
        mime_type = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
        data_uri = f"data:{mime_type};base64,{base64_image}"

        # Run depth estimation
        # Using Flux Depth model
        output = replicate.run(
            "black-forest-labs/flux-1.1-pro",
            input={
                "prompt": "depth map estimation, grayscale depth visualization where brighter areas are closer/higher and darker areas are farther/lower, architectural stadium seating depth analysis",
                "image": data_uri,
                "guidance": 3.5,
                "num_outputs": 1,
                "aspect_ratio": "custom",
                "output_format": "png",
                "output_quality": 90,
                "num_inference_steps": 28,
            }
        )

        # The output is a URL to the generated image
        if output and len(output) > 0:
            import requests
            response = requests.get(output[0])
            return Image.open(io.BytesIO(response.content))

        raise RuntimeError("Depth estimation failed - no output returned")

    def estimate_depth_marigold(self, image_path: Path) -> Image.Image:
        """
        Alternative depth estimation using Marigold model.
        This is specifically designed for monocular depth estimation.

        Args:
            image_path: Path to the seatmap image

        Returns:
            PIL Image containing the depth map
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        # Read the image
        with open(image_path, "rb") as f:
            image_data = f.read()

        base64_image = base64.b64encode(image_data).decode("utf-8")
        mime_type = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
        data_uri = f"data:{mime_type};base64,{base64_image}"

        # Run Marigold depth estimation
        output = replicate.run(
            "adirik/marigold:1a363593bc4882684fc58042d19db5e13a810e44e02f8d4c32afd1eb30464818",
            input={
                "image": data_uri,
                "num_inference_steps": 10,
                "ensemble_size": 10,
            }
        )

        # Output contains depth_np (numpy) and depth_colored (visualization)
        if output and "depth_colored" in output:
            import requests
            response = requests.get(output["depth_colored"])
            return Image.open(io.BytesIO(response.content))

        raise RuntimeError("Depth estimation failed - no output returned")

    def analyze_depth_for_tiers(
        self,
        depth_image: Image.Image,
        num_tiers: int = 3
    ) -> list[dict]:
        """
        Analyze a depth map to suggest tier elevations.

        Args:
            depth_image: PIL Image of the depth map
            num_tiers: Number of tiers to detect

        Returns:
            List of tier suggestions with estimated elevations
        """
        import numpy as np

        # Convert to grayscale numpy array
        gray = depth_image.convert("L")
        arr = np.array(gray)

        # Find depth distribution
        hist, bins = np.histogram(arr.flatten(), bins=50)

        # Find peaks in histogram (representing different tiers)
        from scipy.signal import find_peaks
        try:
            peaks, _ = find_peaks(hist, distance=10, prominence=100)
        except ImportError:
            # If scipy not available, use simple approach
            peaks = np.linspace(0, 49, num_tiers + 2)[1:-1].astype(int)

        # Map peaks to elevation suggestions
        tiers = []
        elevations = [5, 15, 28, 40]  # Standard elevation presets

        for i, peak_idx in enumerate(peaks[:num_tiers]):
            depth_value = bins[peak_idx]
            # Normalize depth to 0-1 (assuming brighter = higher)
            normalized = depth_value / 255.0

            tiers.append({
                "tier_number": (i + 1) * 100,
                "depth_value": float(depth_value),
                "suggested_elevation": elevations[min(i, len(elevations) - 1)],
                "confidence": "medium",
            })

        return tiers
