import gc
import random
import argparse
from collections import OrderedDict
from pathlib import Path

import numpy as np
import torch
from diffusers import DiffusionPipeline
from PIL import Image

# ====================================================
# Device Setup
# ====================================================

device = "cpu"  # Force CPU
torch_dtype = torch.float32

# ====================================================
# Configuration
# ====================================================

MAX_CACHED_MODELS = 2
MAX_SEED = np.iinfo(np.int32).max
MAX_IMAGE_SIZE = 1024

# ====================================================
# Preset Models
# ====================================================

MODELS = {
    "SDXL Turbo": "stabilityai/sdxl-turbo",
    "Juggernaut XL": "RunDiffusion/Juggernaut-XL-v9",
    "RealVis XL": "SG161222/RealVisXL_V5.0",
    "DreamShaper XL": "Lykon/dreamshaper-xl",
}

# ====================================================
# Cache
# ====================================================

loaded_models = OrderedDict()
current_model_name = None

# ====================================================
# Memory Management
# ====================================================

def clear_memory():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def unload_all_models():
    global current_model_name
    for pipe in loaded_models.values():
        del pipe
    loaded_models.clear()
    current_model_name = None
    clear_memory()


# ====================================================
# Model Loading
# ====================================================

def load_pipeline(model_name):
    global current_model_name

    model_id = MODELS.get(model_name, model_name)

    # Already Cached
    if model_name in loaded_models:
        pipe = loaded_models.pop(model_name)
        loaded_models[model_name] = pipe
        current_model_name = model_name
        print(f"✓ Using cached model: {model_name}")
        return pipe

    clear_memory()

    try:
        print(f"📥 Loading model: {model_id}")
        pipe = DiffusionPipeline.from_pretrained(
            model_id,
            torch_dtype=torch_dtype,
        )
        pipe = pipe.to(device)
        print(f"✓ Model loaded successfully")

    except Exception as e:
        clear_memory()
        raise RuntimeError(
            f"Failed to load model:\n"
            f"{model_id}\n"
            f"{type(e).__name__}: {e}"
        )

    loaded_models[model_name] = pipe
    current_model_name = model_name

    # LRU Cache - remove oldest if exceeds limit
    while len(loaded_models) > MAX_CACHED_MODELS:
        oldest_name, oldest_pipe = loaded_models.popitem(last=False)
        print(f"🗑️  Removing cached model: {oldest_name}")
        del oldest_pipe
        clear_memory()

    return pipe


# ====================================================
# Generation Helper
# ====================================================

def generate_image(
    pipe,
    prompt,
    negative_prompt,
    guidance_scale,
    num_inference_steps,
    width,
    height,
    generator,
):
    try:
        print(f"🎨 Generating image: {width}x{height} @ {num_inference_steps} steps")
        result = pipe(
            prompt=prompt,
            negative_prompt=negative_prompt,
            guidance_scale=guidance_scale,
            num_inference_steps=num_inference_steps,
            width=width,
            height=height,
            generator=generator,
        )
        return result.images[0]

    except torch.cuda.OutOfMemoryError:
        clear_memory()
        raise RuntimeError(
            "GPU out of memory.\n"
            "Try lowering image size or using a smaller model."
        )

    except Exception as e:
        clear_memory()
        raise RuntimeError(f"Generation failed:\n{e}")


# ====================================================
# Inference
# ====================================================

def infer(
    model_name,
    custom_model,
    prompt,
    negative_prompt,
    seed,
    randomize_seed,
    width,
    height,
    guidance_scale,
    num_inference_steps,
    output_path,
):
    try:
        if randomize_seed:
            seed = random.randint(0, MAX_SEED)
            print(f"🎲 Randomized seed: {seed}")
        else:
            print(f"🔒 Using seed: {seed}")

        selected_model = (
            custom_model.strip() if custom_model.strip() else model_name
        )

        print(f"📌 Model: {selected_model}")
        print(f"📝 Prompt: {prompt}")
        if negative_prompt:
            print(f"❌ Negative prompt: {negative_prompt}")

        pipe = load_pipeline(selected_model)

        generator = torch.Generator(device=device).manual_seed(seed)

        image = generate_image(
            pipe=pipe,
            prompt=prompt,
            negative_prompt=negative_prompt,
            guidance_scale=guidance_scale,
            num_inference_steps=num_inference_steps,
            width=width,
            height=height,
            generator=generator,
        )

        # Save image
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path)
        print(f"✓ Image saved to: {output_path}")

        return image, seed

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        raise


# ====================================================
# CLI Interface
# ====================================================

def main():
    parser = argparse.ArgumentParser(
        description="Text-to-Image Generation CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_image_cli.py "A beautiful sunset over mountains"
  python generate_image_cli.py "An astronaut in space" --model "SDXL Turbo" --steps 20
  python generate_image_cli.py "A cat" --width 512 --height 512 --seed 42 --output result.png
  python generate_image_cli.py "A dog" --custom-model "stabilityai/sdxl-turbo"
        """,
    )

    # Required arguments
    parser.add_argument(
        "prompt",
        type=str,
        help="Text prompt for image generation",
    )

    # Model selection
    parser.add_argument(
        "--model",
        type=str,
        choices=list(MODELS.keys()),
        default="SDXL Turbo",
        help="Preset model to use (default: SDXL Turbo)",
    )

    parser.add_argument(
        "--custom-model",
        type=str,
        default="",
        help="Custom Hugging Face model ID (overrides --model)",
    )

    # Generation parameters
    parser.add_argument(
        "--negative-prompt",
        type=str,
        default="",
        help="Negative prompt (what to avoid)",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Random seed for reproducibility (default: 0)",
    )

    parser.add_argument(
        "--randomize-seed",
        action="store_true",
        help="Randomize seed (ignores --seed if set)",
    )

    # Image dimensions
    parser.add_argument(
        "--width",
        type=int,
        default=1024,
        help=f"Image width in pixels (default: 1024, max: {MAX_IMAGE_SIZE})",
    )

    parser.add_argument(
        "--height",
        type=int,
        default=1024,
        help=f"Image height in pixels (default: 1024, max: {MAX_IMAGE_SIZE})",
    )

    # Inference parameters
    parser.add_argument(
        "--guidance-scale",
        type=float,
        default=1.0,
        help="CFG guidance scale (default: 1.0, range: 0-20)",
    )

    parser.add_argument(
        "--steps",
        type=int,
        default=4,
        help="Number of inference steps (default: 4, range: 1-50)",
    )

    # Output
    parser.add_argument(
        "--output",
        type=str,
        default="output.png",
        help="Output image path (default: output.png)",
    )

    # Utility
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List available preset models and exit",
    )

    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear model cache and exit",
    )

    args = parser.parse_args()

    # Handle utility commands
    if args.list_models:
        print("Available preset models:")
        for name, model_id in MODELS.items():
            print(f"  {name}: {model_id}")
        return

    if args.clear_cache:
        print("Clearing model cache...")
        unload_all_models()
        print("✓ Cache cleared")
        return

    # Validate dimensions
    if args.width > MAX_IMAGE_SIZE or args.height > MAX_IMAGE_SIZE:
        parser.error(
            f"Image dimensions cannot exceed {MAX_IMAGE_SIZE}x{MAX_IMAGE_SIZE}"
        )

    if args.width % 32 != 0 or args.height % 32 != 0:
        parser.error("Width and height must be multiples of 32")

    # Validate guidance scale
    if not 0 <= args.guidance_scale <= 20:
        parser.error("Guidance scale must be between 0 and 20")

    # Validate steps
    if not 1 <= args.steps <= 50:
        parser.error("Steps must be between 1 and 50")

    # Run inference
    print("=" * 60)
    print("Text-to-Image Generation")
    print("=" * 60)
    try:
        image, seed = infer(
            model_name=args.model,
            custom_model=args.custom_model,
            prompt=args.prompt,
            negative_prompt=args.negative_prompt,
            seed=args.seed,
            randomize_seed=args.randomize_seed,
            width=args.width,
            height=args.height,
            guidance_scale=args.guidance_scale,
            num_inference_steps=args.steps,
            output_path=args.output,
        )
        print("=" * 60)
        print("✓ Generation complete!")
        print("=" * 60)
    except Exception as e:
        print("=" * 60)
        print("❌ Generation failed")
        print("=" * 60)
        raise


if __name__ == "__main__":
    main()
