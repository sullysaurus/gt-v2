"""Client for calling the Modal render backend."""
import hashlib
import os
from pathlib import Path
from typing import Optional

from app.models.camera import CameraPosition
from app.models.venue import Venue
from app.config import CACHE_DIR, CACHE_ENABLED, CACHE_POSITION_PRECISION, MODAL_TOKEN_ID, MODAL_TOKEN_SECRET


def _configure_modal():
    """Configure Modal credentials from config."""
    if MODAL_TOKEN_ID and MODAL_TOKEN_SECRET:
        os.environ["MODAL_TOKEN_ID"] = MODAL_TOKEN_ID
        os.environ["MODAL_TOKEN_SECRET"] = MODAL_TOKEN_SECRET


class RenderClient:
    """Client for rendering seat views via Modal."""

    def __init__(self, venue: Venue):
        self.venue = venue
        self._ensure_cache_dir()

    def _ensure_cache_dir(self):
        """Create cache directory if it doesn't exist."""
        if CACHE_ENABLED:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _get_cache_key(self, camera: CameraPosition) -> str:
        """Generate a cache key from camera position."""
        # Round position to reduce cache variations
        rounded = (
            round(camera.x / CACHE_POSITION_PRECISION) * CACHE_POSITION_PRECISION,
            round(camera.y / CACHE_POSITION_PRECISION) * CACHE_POSITION_PRECISION,
            round(camera.z / CACHE_POSITION_PRECISION) * CACHE_POSITION_PRECISION,
        )

        key_str = f"{self.venue.id}_{rounded[0]}_{rounded[1]}_{rounded[2]}"
        return hashlib.md5(key_str.encode()).hexdigest()

    def _get_cached(self, cache_key: str) -> Optional[bytes]:
        """Try to get a cached render."""
        if not CACHE_ENABLED:
            return None

        cache_path = CACHE_DIR / f"{cache_key}.png"
        if cache_path.exists():
            return cache_path.read_bytes()
        return None

    def _save_to_cache(self, cache_key: str, image_data: bytes):
        """Save a render to cache."""
        if CACHE_ENABLED:
            cache_path = CACHE_DIR / f"{cache_key}.png"
            cache_path.write_bytes(image_data)

    def render(
        self,
        camera: CameraPosition,
        width: int = 1920,
        height: int = 1080,
        samples: int = 64,
        use_cache: bool = True,
    ) -> bytes:
        """
        Render a view from the given camera position.

        Args:
            camera: Camera position and orientation
            width: Render width in pixels
            height: Render height in pixels
            samples: Number of render samples (higher = better quality but slower)
            use_cache: Whether to use cached renders

        Returns:
            PNG image data as bytes
        """
        # Check cache first
        if use_cache:
            cache_key = self._get_cache_key(camera)
            cached = self._get_cached(cache_key)
            if cached:
                return cached

        # Configure Modal credentials and import
        _configure_modal()
        import modal

        # Import the Modal function
        render_fn = modal.Function.lookup("seat-view-renderer", "render_seat_view")

        # Call the render function
        image_data = render_fn.remote(
            venue_id=self.venue.id,
            template_name=self.venue.template,
            camera_x=camera.x,
            camera_y=camera.y,
            camera_z=camera.z,
            rotation_x=camera.rotation.x,
            rotation_y=camera.rotation.y,
            rotation_z=camera.rotation.z,
            fov=camera.fov,
            width=width,
            height=height,
            samples=samples,
        )

        # Save to cache
        if use_cache:
            self._save_to_cache(cache_key, image_data)

        return image_data

    def render_preview(self, camera: CameraPosition) -> bytes:
        """Render a quick preview (lower quality, faster)."""
        return self.render(
            camera=camera,
            width=960,
            height=540,
            samples=16,
            use_cache=True,
        )

    def render_full(self, camera: CameraPosition) -> bytes:
        """Render a full quality image."""
        return self.render(
            camera=camera,
            width=1920,
            height=1080,
            samples=64,
            use_cache=True,
        )
