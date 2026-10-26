"""Stand-in for a real AI image generator, for testing the AUTOEDIT_IMAGE_CMD hook.

Usage: AUTOEDIT_IMAGE_CMD='python3 tools/demo_image_gen.py --prompt {prompt} --out {out}'
It draws an abstract gradient (it is NOT an AI model) so the pipeline can be exercised offline.
Replace it with a script that calls your image API and writes a PNG/JPG to --out.
"""
import argparse
import hashlib

import numpy as np
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument("--prompt", required=True)
ap.add_argument("--out", required=True)
a = ap.parse_args()
seed = int(hashlib.md5(a.prompt.encode()).hexdigest()[:8], 16)
rng = np.random.default_rng(seed)
yy, xx = np.mgrid[0:1024, 0:1024] / 1024.0
cx, cy = rng.uniform(0.3, 0.7, 2)
glow = np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / 0.05)[..., None]
img = np.array([10, 9, 12]) + glow * np.array([255, 150, 30]) + rng.normal(0, 4, (1024, 1024, 3))
Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(a.out)
