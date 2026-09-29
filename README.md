# Real 3D Print — CMYK+W Layer Dithering for FDM

Print **any color** on a standard FDM printer using five base filaments:
**Cyan · Magenta · Yellow · Black · White**

Load them into your AMS once. The tool generates a layer-dithered `.3mf` that
Bambu Studio opens directly — no slicer plugins required.

## How it works

FDM printers can only use one filament per layer. Real 3D Print converts a target
color into a sequence of CMYK+W layers using dithering, the same technique used in
every inkjet printer for 40 years.

```
Target: #FF6600 (orange)  →  M=37.5%  Y=62.5%  →  MYYMYYMY... (10 layers)
```

The Python CLI handles the math. The Bambu Studio plugin (companion fork) handles
the slicer integration.

## Quick start

```bash
# Terminal preview
python main.py "#FF6600"

# Generate a 20×20mm test swatch as .3mf
python main.py "#FF6600" --3mf swatch.3mf

# Open swatch.3mf in Bambu Studio, print with CMYKW AMS setup
```

## AMS slot assignment

| Slot | Filament | Hex     |
|------|----------|---------|
| 1    | Cyan     | #00FFFF |
| 2    | Magenta  | #FF00FF |
| 3    | Yellow   | #FFFF00 |
| 4    | Black    | #1A1A1A |
| 5    | White    | #FFFFFF |

## CLI reference

```
python main.py [HEX_COLOR] [OPTIONS]

  HEX_COLOR             Target color (default: #FF6B35)
  --layers N            Number of layers to dither (default: 10)
  --grid WxH            Dithering grid size (default: 12x12)
  --algo bayer|fs       Dithering algorithm: Bayer 4×4 or Floyd-Steinberg
  --optimize            Apply greedy TSP purge optimizer (85-93% reduction)
  --threshold N         Minimum consecutive layers per filament
  --4fil                4-filament mode (no white)
  --3mf FILE            Generate test swatch as .3mf
  --process FILE.3mf    Convert an existing colored .3mf to CMYK+W dithered
  --gradient A B N      Gradient between two colors in N steps
  --delta               Show Delta-E 2000 color accuracy (now shown by default)
  --png FILE            Save dithering grid as PNG (requires matplotlib)
```

## Modules

| File            | Purpose                                           |
|-----------------|---------------------------------------------------|
| `color.py`      | RGB → CMYK+W analytical conversion               |
| `colormath.py`  | RGB → LAB, Delta-E 2000 (Sharma et al.)          |
| `calibration.py`| Physical filament profiles, NNLS fitting          |
| `dither.py`     | Bayer 4×4 and bidirectional Floyd-Steinberg in LAB|
| `optimizer.py`  | Greedy TSP purge optimizer                        |
| `generator.py`  | 3MF multimaterial file generator                  |
| `preview.py`    | Terminal preview: target vs achievable + ΔE       |
| `main.py`       | CLI entry point                                   |

## Color accuracy

Delta-E 2000 measures perceptual color difference (< 3 = imperceptible, < 6 = acceptable):

| Color  | Target  | Achievable | ΔE   |
|--------|---------|------------|------|
| Orange | #FF6600 | #FF9F5F    | 12.9 |
| Blue   | #3366CC | #5580D4    | 9.3  |
| Brown  | #8B4513 | #9E633A    | 10.3 |

High ΔE for saturated colors is expected: FDM layer dithering (one filament per
layer) cannot exceed 100% total coverage, so fully saturated colors are
inherently desaturated compared to inkjet. Use `--calibrate-profile` with
measured filament spectral data to improve accuracy.

## Bambu Studio integration

This CLI is the companion tool for the
[Real 3D Print BambuStudio fork](https://github.com/Souzafilipe91/BambuStudio/tree/feature/cmykw-color-decompose).

The fork adds a **CMYK+W** card to the "Decompose Color" dialog. When you click OK,
it shows the channel breakdown and the exact `python main.py ...` command to run.

## Requirements

- Python 3.10+
- No dependencies for core functionality
- `matplotlib` optional (for `--png`)

## Roadmap

- [x] Phase 1 — Python CLI: HEX → layer sequence → `.3mf`
- [x] Phase 2 — BambuStudio dialog: CMYK+W decomposition card
- [ ] Phase 3 — Native slicer integration: layer dithering in painting pipeline
- [ ] Phase 4 — Calibrated filament kit + preset bundle
