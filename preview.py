"""
Visualização dos resultados no terminal e via matplotlib (opcional).
"""

from __future__ import annotations
import sys
import io

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from color import FILAMENT_RGB, FILAMENTS, cmykw_to_rgb_preview, hex_to_rgb

FILAMENT_ANSI = {
    'C': '\033[96m',
    'M': '\033[95m',
    'Y': '\033[93m',
    'K': '\033[90m',
    'W': '\033[97m',
}
RESET = '\033[0m'
BLOCK = '██'


def _ansi_color(r8: int, g8: int, b8: int) -> str:
    return f'\033[38;2;{r8};{g8};{b8}m'


def print_cmykw(hex_input: str, cmykw: dict[str, float]) -> None:
    target_rgb = hex_to_rgb(hex_input)
    tr8 = int(target_rgb[0] * 255)
    tg8 = int(target_rgb[1] * 255)
    tb8 = int(target_rgb[2] * 255)

    preview_rgb = cmykw_to_rgb_preview(cmykw)
    pr8 = int(preview_rgb[0] * 255)
    pg8 = int(preview_rgb[1] * 255)
    pb8 = int(preview_rgb[2] * 255)

    try:
        from colormath import delta_e
        de = delta_e(target_rgb, preview_rgb)
        de_str = f"  ΔE={de:.1f}"
        if de < 3:
            de_label = " (imperceptível)"
        elif de < 6:
            de_label = " (aceitável)"
        elif de < 12:
            de_label = " (visível)"
        else:
            de_label = " (alto)"
        de_display = de_str + de_label
    except Exception:
        de_display = ""

    print(f"\nAlvo     : {_ansi_color(tr8, tg8, tb8)}{BLOCK}{RESET}  {hex_input}  (RGB {tr8}, {tg8}, {tb8})")
    print(f"Dithering: {_ansi_color(pr8, pg8, pb8)}{BLOCK}{RESET}  (RGB {pr8}, {pg8}, {pb8}){de_display}")
    print("Proporções CMYK+W:")
    for f in FILAMENTS:
        v = cmykw.get(f, 0.0)
        bar_len = int(v * 30)
        bar = FILAMENT_ANSI[f] + '█' * bar_len + RESET
        print(f"  {f}  {bar}  {v:.1%}")


def print_layer_sequence(sequence: list[str], max_display: int = 40) -> None:
    print(f"\nSequência de camadas ({len(sequence)} total):")
    display = sequence[:max_display]
    colored = ''.join(FILAMENT_ANSI[f] + f + RESET for f in display)
    suffix = '...' if len(sequence) > max_display else ''
    print(f"  {colored}{suffix}")

    from dither import layer_summary
    summary = layer_summary(sequence)
    print("  Contagem:", "  ".join(f"{f}:{n}" for f, n in summary.items() if n > 0))


def print_grid(grid: list[list[str]], label: str = "Grade de dithering") -> None:
    print(f"\n{label} ({len(grid[0])}x{len(grid)} pontos):")
    for row in grid:
        print('  ' + ''.join(FILAMENT_ANSI[f] + '█' + RESET for f in row))


def save_png(
    hex_input: str,
    cmykw: dict[str, float],
    grid: list[list[str]],
    path: str,
) -> None:
    try:
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        import numpy as np
    except ImportError:
        print("matplotlib não instalado — PNG não gerado.")
        return

    fig, axes = plt.subplots(1, 3, figsize=(14, 5))
    fig.suptitle(f"Real 3D Print — {hex_input}", fontsize=14)

    r, g, b = [int(hex_input.lstrip('#')[i:i+2], 16) / 255 for i in (0, 2, 4)]
    axes[0].add_patch(mpatches.FancyBboxPatch((0.1, 0.1), 0.8, 0.8, color=(r, g, b)))
    axes[0].set_xlim(0, 1)
    axes[0].set_ylim(0, 1)
    axes[0].set_title("Cor alvo")
    axes[0].axis('off')

    filament_colors_mpl = {f: FILAMENT_RGB[f] for f in FILAMENTS}
    bars = axes[1].bar(
        list(cmykw.keys()),
        list(cmykw.values()),
        color=[filament_colors_mpl[f] for f in cmykw],
        edgecolor='gray',
    )
    axes[1].set_ylim(0, 1)
    axes[1].set_title("Proporções CMYK+W")
    axes[1].set_ylabel("Fração")
    for bar, (f, v) in zip(bars, cmykw.items()):
        axes[1].text(bar.get_x() + bar.get_width() / 2, v + 0.02, f"{v:.0%}", ha='center', fontsize=9)

    np_grid = np.array([[FILAMENT_RGB[cell] for cell in row] for row in grid])
    axes[2].imshow(np_grid, interpolation='nearest')
    axes[2].set_title("Padrão de dithering (grid)")
    axes[2].axis('off')

    plt.tight_layout()
    plt.savefig(path, dpi=150)
    print(f"\nPNG salvo em: {path}")
    plt.close()
