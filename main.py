"""
Real 3D Print — CLI de teste completo.

Uso:
  python main.py #FF6B35
  python main.py #FF6B35 --layers 20 --grid 16x16
  python main.py #FF6B35 --algo fs              (Floyd-Steinberg)
  python main.py #FF6B35 --optimize             (purge optimizer)
  python main.py #FF6B35 --threshold 3          (threshold de troca)
  python main.py #FF6B35 --4fil                 (modo 4 filamentos)
  python main.py #FF6B35 --delta                (Delta-E)
  python main.py --gradient #FF0000 #0000FF 8   (gradiente)
  python main.py --calibrate                    (relatório de calibração padrão)
"""

import argparse
import sys
import io
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from color import hex_to_cmykw, hex_to_rgb, describe, cmykw_to_rgb_preview
from dither import layer_sequence, grid_dither, floyd_steinberg, layer_summary
from optimizer import optimize_sequence, purge_report, apply_threshold, gradient_cmykw, to_4_filament
from colormath import delta_e, color_accuracy_report
from calibration import FilamentProfile, default_profile
from preview import print_cmykw, print_layer_sequence, print_grid


def run_single(args: argparse.Namespace, profile: FilamentProfile) -> None:
    hex_color = args.hex_color if args.hex_color.startswith('#') else f"#{args.hex_color}"

    try:
        grid_w, grid_h = (int(x) for x in args.grid.lower().split('x'))
    except ValueError:
        print(f"Formato de grade inválido: {args.grid}")
        sys.exit(1)

    # Conversão principal
    if args.calibrate_profile:
        cmykw = profile.calibrate(hex_to_rgb(hex_color))
        print(f"\n[Modo calibrado] perfil carregado de {args.calibrate_profile}")
    else:
        cmykw = hex_to_cmykw(hex_color)

    # Modo 4 filamentos
    if getattr(args, 'four_fil', False):
        cmykw_4 = to_4_filament(cmykw)
        print(f"\n[Modo 4 filamentos — sem branco]")
        print(f"  5 fil: {describe(cmykw)}")
        print(f"  4 fil: {describe(cmykw_4)}")
        cmykw = cmykw_4

    print_cmykw(hex_color, cmykw)
    print(f"\n  → {describe(cmykw)}")

    # Delta-E
    if args.delta:
        sim_rgb = cmykw_to_rgb_preview(cmykw)
        target_rgb = hex_to_rgb(hex_color)
        report = color_accuracy_report(target_rgb, sim_rgb)
        print(f"\nDelta-E 2000: {report['delta_e']}  ({report['label']})")

    # Sequência de camadas
    sequence = layer_sequence(cmykw, args.layers)

    if args.threshold > 1:
        sequence_thresh = apply_threshold(sequence, args.threshold)
        print(f"\n[Threshold = {args.threshold} camadas]")
        print(f"  Antes:  {len(set(zip(sequence, sequence[1:])))} trocas")
        trocas_depois = sum(1 for i in range(1, len(sequence_thresh)) if sequence_thresh[i] != sequence_thresh[i-1])
        print(f"  Depois: {trocas_depois} trocas")
        sequence = sequence_thresh

    if args.optimize:
        optimized = optimize_sequence(sequence)
        report_p = purge_report(sequence, optimized)
        print(f"\n[Purge Optimizer]")
        print(f"  Custo original:   {report_p['original_cost']}  ({report_p['original_switches']} trocas)")
        print(f"  Custo otimizado:  {report_p['optimized_cost']}  ({report_p['optimized_switches']} trocas)")
        print(f"  Redução de purga: {report_p['reduction_pct']}%")
        sequence = optimized

    print_layer_sequence(sequence)

    # Grade de dithering
    if args.algo == 'fs':
        print(f"\n[Floyd-Steinberg]")
        grid = floyd_steinberg(cmykw, grid_w, grid_h)
    else:
        print(f"\n[Bayer 4×4]")
        grid = grid_dither(cmykw, grid_w, grid_h)

    print_grid(grid)

    if args.png:
        from preview import save_png
        save_png(hex_color, cmykw, grid, args.png)

    if args.gen_3mf:
        from generator import generate_swatch
        generate_swatch(
            hex_color,
            n_layers=args.layers,
            optimize=args.optimize,
            output_path=args.gen_3mf,
        )

    if args.process:
        from generator import process_model
        out_dir = str(Path(args.process).parent)
        process_model(args.process, output_path=out_dir,
                      n_layers=args.layers, optimize=args.optimize)


def run_gradient(args: argparse.Namespace) -> None:
    color_a, color_b, steps = args.gradient
    steps = int(steps)
    perceptual = not args.rgb_interp

    mode = "LAB perceptual" if perceptual else "RGB linear"
    print(f"\nGradiente {color_a} → {color_b}  ({steps} passos, interpolação {mode})\n")

    gradient = gradient_cmykw(color_a, color_b, steps, perceptual=perceptual)
    for i, cmykw in enumerate(gradient):
        t = i / max(steps - 1, 1)
        print(f"  Passo {i+1:02d} (t={t:.2f})  {describe(cmykw)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Real 3D Print — algoritmos CMYK+W para FDM")

    parser.add_argument('hex_color', nargs='?', default='#FF6B35',
                        help='Cor alvo em HEX (ex: #FF6B35)')
    parser.add_argument('--layers', type=int, default=10)
    parser.add_argument('--grid', default='12x12')
    parser.add_argument('--algo', choices=['bayer', 'fs'], default='bayer',
                        help='bayer (padrão) ou fs (Floyd-Steinberg)')
    parser.add_argument('--optimize', action='store_true', help='Aplicar purge optimizer')
    parser.add_argument('--threshold', type=int, default=1, metavar='N',
                        help='Mínimo de camadas consecutivas por filamento')
    parser.add_argument('--4fil', dest='four_fil', action='store_true',
                        help='Modo 4 filamentos sem branco')
    parser.add_argument('--delta', action='store_true', help='Calcular Delta-E 2000')
    parser.add_argument('--calibrate-profile', metavar='ARQUIVO',
                        help='Usar perfil de calibração JSON')
    parser.add_argument('--png', metavar='ARQUIVO', help='Salvar PNG (requer matplotlib)')
    parser.add_argument('--gradient', nargs=3, metavar=('COR_A', 'COR_B', 'PASSOS'),
                        help='Gradiente entre duas cores (ex: --gradient #FF0000 #0000FF 8)')
    parser.add_argument('--rgb-interp', action='store_true',
                        help='Interpolar gradiente em RGB em vez de LAB')
    parser.add_argument('--3mf', dest='gen_3mf', metavar='ARQUIVO',
                        help='Gerar swatch 3MF para o slicer (ex: --3mf swatch.3mf)')
    parser.add_argument('--process', metavar='ARQUIVO_3MF',
                        help='Processar 3MF colorido existente e gerar versão CMYK+W')

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.gradient:
        run_gradient(args)
        return

    profile = (
        FilamentProfile.load(args.calibrate_profile)
        if args.calibrate_profile
        else default_profile()
    )

    run_single(args, profile)


if __name__ == '__main__':
    main()
