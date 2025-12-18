"""AI-powered view generator for creating photorealistic seat views."""
import base64
import io
import math
import replicate
import requests
from pathlib import Path
from typing import Optional, Union
from PIL import Image

from app.config import REPLICATE_API_TOKEN
from app.models.camera import CameraPosition


class ViewGenerator:
    """
    Generates photorealistic seat views using AI.

    Workflow:
    1. Take a reference image of the venue
    2. Analyze it to understand the visual style and scene
    3. When user selects a seat, generate a new view from that perspective
    """

    def __init__(self, api_token: Optional[str] = None):
        self.api_token = api_token or REPLICATE_API_TOKEN
        if not self.api_token:
            raise ValueError("REPLICATE_API_TOKEN is required")

        # Store reference image data
        self.reference_image: Optional[Image.Image] = None
        self.reference_depth: Optional[Image.Image] = None
        self.venue_description: Optional[str] = None

    def _image_to_data_uri(self, image: Union[Path, Image.Image, bytes]) -> str:
        """Convert image to data URI for API."""
        if isinstance(image, Path):
            with open(image, "rb") as f:
                image_bytes = f.read()
            suffix = image.suffix.lower()
        elif isinstance(image, Image.Image):
            buffer = io.BytesIO()
            # Convert to RGB if necessary (handles RGBA, P mode, etc.)
            if image.mode in ('RGBA', 'P', 'LA'):
                image = image.convert('RGB')
            image.save(buffer, format="PNG")
            buffer.seek(0)
            image_bytes = buffer.read()
            suffix = ".png"
        else:
            image_bytes = image
            suffix = ".png"

        if image_bytes is None:
            raise ValueError("Failed to convert image to bytes")

        mime_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(suffix, "image/png")

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        return f"data:{mime_type};base64,{b64}"

    def set_reference_image(
        self,
        image: Union[Path, Image.Image, bytes],
        venue_type: str = "baseball",
        description: Optional[str] = None
    ) -> dict:
        """
        Set the reference image for view generation.

        Args:
            image: Reference photo of the venue
            venue_type: Type of venue (baseball, hockey, basketball, etc.)
            description: Optional description of the venue

        Returns:
            Analysis results including detected features
        """
        # Load image
        if isinstance(image, Path):
            self.reference_image = Image.open(image)
        elif isinstance(image, bytes):
            self.reference_image = Image.open(io.BytesIO(image))
        else:
            self.reference_image = image

        # Generate depth map of reference
        self.reference_depth = self._estimate_depth(self.reference_image)

        # Build venue description
        venue_descriptions = {
            "baseball": "professional baseball stadium with green grass field, dirt infield, stadium seating, crowd, bright daylight",
            "hockey": "indoor hockey arena with ice rink, hockey boards, arena seating, overhead lighting",
            "basketball": "indoor basketball arena with hardwood court, basketball hoops, arena seating",
            "football": "football stadium with grass field, yard lines, goalposts, stadium seating",
            "soccer": "soccer stadium with grass pitch, goals, stadium seating",
            "concert": "concert venue with stage, lighting rigs, audience seating",
        }

        self.venue_description = description or venue_descriptions.get(
            venue_type,
            "large venue with seating and central field/stage area"
        )

        return {
            "reference_size": self.reference_image.size,
            "depth_generated": self.reference_depth is not None,
            "venue_type": venue_type,
            "description": self.venue_description,
        }

    def _estimate_depth(self, image: Image.Image) -> Image.Image:
        """Generate depth map using Marigold."""
        client = replicate.Client(api_token=self.api_token)
        image_uri = self._image_to_data_uri(image)

        try:
            output = client.run(
                "adirik/marigold:1a363593bc4882684fc58042d19db5e13a810e44e02f8d4c32afd1eb30464818",
                input={
                    "image": image_uri,
                    "num_inference_steps": 10,
                    "ensemble_size": 5,
                }
            )

            if output and "depth_colored" in output:
                response = requests.get(output["depth_colored"])
                return Image.open(io.BytesIO(response.content))
        except Exception as e:
            print(f"Depth estimation failed: {e}")

        return None

    def _camera_to_prompt_hints(self, camera: CameraPosition) -> str:
        """Convert camera position to prompt hints for view perspective."""
        hints = []

        # Height-based hints
        if camera.z < 10:
            hints.append("low angle view from field level")
        elif camera.z < 20:
            hints.append("mid-level seating view")
        elif camera.z < 35:
            hints.append("upper deck elevated view")
        else:
            hints.append("high nosebleed section view looking down")

        # Angle-based hints (assuming 0 = behind home plate for baseball)
        angle = math.degrees(math.atan2(camera.y, camera.x))
        if -30 <= angle <= 30:
            hints.append("behind home plate")
        elif 30 < angle <= 70:
            hints.append("along first base line")
        elif 70 < angle <= 110:
            hints.append("right field view")
        elif -70 <= angle < -30:
            hints.append("along third base line")
        elif -110 <= angle < -70:
            hints.append("left field view")
        else:
            hints.append("outfield view looking toward home plate")

        # Distance hints
        distance = math.sqrt(camera.x**2 + camera.y**2)
        if distance < 40:
            hints.append("close to the action")
        elif distance < 70:
            hints.append("mid-distance view")
        else:
            hints.append("distant panoramic view")

        return ", ".join(hints)

    def generate_view(
        self,
        camera: CameraPosition,
        venue_type: str = "baseball",
        width: int = 1024,
        height: int = 768,
        use_reference_style: bool = True,
    ) -> bytes:
        """
        Generate a photorealistic view from the specified seat position.

        Args:
            camera: Camera position representing the seat view
            venue_type: Type of venue for context
            width: Output image width
            height: Output image height
            use_reference_style: Whether to use reference image for style

        Returns:
            PNG image data as bytes
        """
        client = replicate.Client(api_token=self.api_token)

        # Build the prompt
        perspective_hints = self._camera_to_prompt_hints(camera)

        base_prompt = self.venue_description or f"professional {venue_type} stadium"

        prompt = f"""Photorealistic photograph of a {base_prompt}, {perspective_hints},
        fan's point of view from their seat, looking at the field/court,
        natural lighting, detailed crowd in surrounding seats,
        high quality DSLR photograph, sharp focus on the playing field"""

        negative_prompt = """blurry, distorted, cartoon, illustration, painting,
        drawing, art, unrealistic, bad perspective, warped, fisheye,
        empty stadium, no crowd, night time (unless specified)"""

        # Choose generation approach based on available reference
        if use_reference_style and self.reference_image:
            # Use img2img with the reference for style consistency
            image_data = self._generate_with_reference(
                client, prompt, negative_prompt, width, height
            )
        else:
            # Pure text-to-image generation
            image_data = self._generate_from_prompt(
                client, prompt, negative_prompt, width, height
            )

        return image_data

    def _generate_with_reference(
        self,
        client: replicate.Client,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
    ) -> bytes:
        """Generate view using reference image for style guidance."""

        reference_uri = self._image_to_data_uri(self.reference_image)

        # Use SDXL with IP-Adapter for style transfer
        # Or use Flux img2img for better results
        try:
            output = client.run(
                "lucataco/sdxl-controlnet-depth:1c8636483aba1aca00a6820c5a2046a5bb5f599ba657605a0ba36b36101f8c55",
                input={
                    "image": reference_uri if self.reference_depth else reference_uri,
                    "prompt": prompt,
                    "negative_prompt": negative_prompt,
                    "num_inference_steps": 30,
                    "guidance_scale": 7.5,
                    "controlnet_conditioning_scale": 0.5,  # Balance between depth guidance and freedom
                    "width": width,
                    "height": height,
                }
            )

            if output:
                response = requests.get(output[0] if isinstance(output, list) else output)
                return response.content

        except Exception as e:
            print(f"ControlNet generation failed: {e}, falling back to img2img")

        # Fallback to standard img2img
        return self._generate_img2img(client, reference_uri, prompt, negative_prompt, width, height)

    def _generate_img2img(
        self,
        client: replicate.Client,
        reference_uri: str,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
    ) -> bytes:
        """Generate using img2img transformation."""
        output = client.run(
            "stability-ai/sdxl:7762fd07cf82c948538e41f63f77d685e02b063e37e496e96eefd46c929f9bdc",
            input={
                "image": reference_uri,
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "num_inference_steps": 30,
                "guidance_scale": 7.5,
                "prompt_strength": 0.7,  # Balance between reference and new perspective
                "width": width,
                "height": height,
            }
        )

        if output:
            response = requests.get(output[0] if isinstance(output, list) else output)
            return response.content

        raise RuntimeError("Image generation failed")

    def _generate_from_prompt(
        self,
        client: replicate.Client,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
    ) -> bytes:
        """Generate view from prompt only (no reference)."""

        # Use Flux for highest quality
        try:
            output = client.run(
                "black-forest-labs/flux-1.1-pro",
                input={
                    "prompt": prompt,
                    "width": width,
                    "height": height,
                    "num_inference_steps": 28,
                    "guidance": 3.5,
                }
            )

            if output:
                url = output[0] if isinstance(output, list) else output
                response = requests.get(url)
                return response.content

        except Exception as e:
            print(f"Flux generation failed: {e}, falling back to SDXL")

        # Fallback to SDXL
        output = client.run(
            "stability-ai/sdxl:7762fd07cf82c948538e41f63f77d685e02b063e37e496e96eefd46c929f9bdc",
            input={
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "num_inference_steps": 30,
                "guidance_scale": 7.5,
                "width": width,
                "height": height,
            }
        )

        if output:
            response = requests.get(output[0] if isinstance(output, list) else output)
            return response.content

        raise RuntimeError("Image generation failed")

    def generate_view_flux(
        self,
        camera: CameraPosition,
        reference_image: Union[Path, Image.Image, bytes],
        venue_type: str = "baseball",
        width: int = 1024,
        height: int = 768,
    ) -> bytes:
        """
        Generate view using Flux with image reference (one-shot method).

        This doesn't require pre-setting a reference - useful for quick generation.
        """
        client = replicate.Client(api_token=self.api_token)

        # Load reference
        if isinstance(reference_image, Path):
            ref_img = Image.open(reference_image)
        elif isinstance(reference_image, bytes):
            ref_img = Image.open(io.BytesIO(reference_image))
        else:
            ref_img = reference_image

        reference_uri = self._image_to_data_uri(ref_img)
        perspective_hints = self._camera_to_prompt_hints(camera)

        prompt = f"""Create a photorealistic photograph showing the exact same {venue_type} stadium
        as in the reference image, but from a different viewpoint: {perspective_hints}.
        Maintain the same lighting, colors, and atmosphere.
        Show the view as a fan would see it from their seat, looking at the field.
        Include surrounding crowd and seats in the foreground."""

        # Use Flux Redux for style-consistent generation
        try:
            output = client.run(
                "black-forest-labs/flux-redux-dev",
                input={
                    "image": reference_uri,
                    "prompt": prompt,
                    "guidance": 3.0,
                    "num_inference_steps": 28,
                    "megapixels": "1",
                }
            )

            if output:
                url = output[0] if isinstance(output, list) else output
                response = requests.get(url)
                return response.content
        except Exception as e:
            print(f"Flux Redux failed: {e}")

        # Fallback to standard generation
        return self._generate_from_prompt(
            client,
            prompt,
            "blurry, distorted, cartoon",
            width,
            height
        )
