"""
Geração de padrões de dithering CMYK+W para FDM.

Dois modos:
  - layer:  dithering por camada inteira (AMS — H2D, X1C, P1P, P1S)
  - grid:   dithering por ponto em grade 2D (H2C — zero purga)
"""

from __future__ import annotations
import math
from color import FILAMENTS


def layer_sequence(cmykw: dict[str, float], n_layers: int) -> list[str]:
    """
    Distribui n_layers entre os filamentos proporcional às suas frações.
    Usa sequência de Bresenham para minimizar erros de arredondamento.

    Retorna lista de n_layers elementos, cada um sendo 'C','M','Y','K' ou 'W'.
    """
    counts: dict[str, int] = {}
    error: dict[str, float] = {f: 0.0 for f in FILAMENTS}

    active = [f for f in FILAMENTS if cmykw.get(f, 0.0) > 1e-9]

    for f in active:
        exact = cmykw[f] * n_layers
        counts[f] = math.floor(exact)
        error[f] = exact - counts[f]

    deficit = n_layers - sum(counts.values())
    for f in sorted(error, key=lambda x: -error[x])[:deficit]:
        counts[f] += 1

    sequence: list[str] = []
    for f in active:
        sequence.extend([f] * counts[f])

    sequence.sort(key=lambda f: -cmykw[f])
    return _interleave(sequence, cmykw)


def _interleave(sequence: list[str], cmykw: dict[str, float]) -> list[str]:
    """
    Reordena a sequência para intercalar os filamentos de forma uniforme,
    evitando blocos contínuos do mesmo material.
    Algoritmo: distribui cada filamento em slots igualmente espaçados.
    """
    if not sequence:
        return sequence

    n = len(sequence)
    result: list[str | None] = [None] * n
    available = sorted(
        [(count, f) for f, count in _count(sequence).items()],
        reverse=True,
    )

    pos = 0
    for count, f in available:
        placed = 0
        step = n / count if count else 1
        start = pos % n
        for i in range(count):
            idx = int(start + i * step) % n
            while result[idx] is not None:
                idx = (idx + 1) % n
            result[idx] = f
            placed += 1

    return [x for x in result if x is not None]


def _count(seq: list[str]) -> dict[str, int]:
    c: dict[str, int] = {}
    for x in seq:
        c[x] = c.get(x, 0) + 1
    return c


def grid_dither(
    cmykw: dict[str, float],
    width: int,
    height: int,
) -> list[list[str]]:
    """
    Gera grade 2D de filamentos via dithering ordenado (Bayer 4x4).
    Cada célula representa um ponto de extrusão.

    Retorna matriz [height][width] com o filamento de cada ponto.
    """
    bayer4 = [
        [ 0,  8,  2, 10],
        [12,  4, 14,  6],
        [ 3, 11,  1,  9],
        [15,  7, 13,  5],
    ]
    bayer_size = 4
    bayer_levels = 16

    sorted_filaments = sorted(
        [(cmykw.get(f, 0.0), f) for f in FILAMENTS if cmykw.get(f, 0.0) > 0.0],
        reverse=True,
    )

    grid: list[list[str]] = []
    for row in range(height):
        grid_row: list[str] = []
        for col in range(width):
            threshold = bayer4[row % bayer_size][col % bayer_size] / bayer_levels
            cumulative = 0.0
            chosen = sorted_filaments[-1][1]
            for proportion, filament in sorted_filaments:
                cumulative += proportion
                if threshold < cumulative:
                    chosen = filament
                    break
            grid_row.append(chosen)
        grid.append(grid_row)

    return grid


def layer_summary(sequence: list[str]) -> dict[str, int]:
    return _count(sequence)


# ---------------------------------------------------------------------------
# Floyd-Steinberg (difusão de erro — qualidade superior ao Bayer)
# ---------------------------------------------------------------------------

def floyd_steinberg(
    cmykw: dict[str, float],
    width: int,
    height: int,
) -> list[list[str]]:
    """
    Dithering por difusão de erro Floyd-Steinberg em grade 2D.

    Para cada célula, escolhe o filamento cuja cor mais se aproxima
    do valor acumulado (alvo + erros difundidos dos vizinhos).
    O erro residual é distribuído para os 4 vizinhos:
        →  7/16   ↙  3/16   ↓  5/16   ↘  1/16

    Resulta em padrões mais orgânicos e menos estruturados que o Bayer,
    especialmente em gradientes e regiões de cor uniforme.
    """
    from colormath import rgb_to_lab
    from color import FILAMENT_RGB

    # Grade de erros acumulados em RGB (float)
    err_r = [[0.0] * width for _ in range(height)]
    err_g = [[0.0] * width for _ in range(height)]
    err_b = [[0.0] * width for _ in range(height)]

    # Cor alvo em RGB (via preview aditivo)
    from color import cmykw_to_rgb_preview
    tr, tg, tb = cmykw_to_rgb_preview(cmykw)

    def nearest_filament(r: float, g: float, b: float) -> str:
        """Filamento mais próximo em espaço LAB (perceptualmente uniforme)."""
        best_f, best_dist = 'W', float('inf')
        try:
            tL, ta, tb_val = rgb_to_lab(
                max(0.0, min(1.0, r)),
                max(0.0, min(1.0, g)),
                max(0.0, min(1.0, b)),
            )
            for f, frgb in FILAMENT_RGB.items():
                if cmykw.get(f, 0.0) < 1e-9:
                    continue
                fL, fa, fb_v = rgb_to_lab(*frgb)
                dist = math.sqrt((tL - fL) ** 2 + (ta - fa) ** 2 + (tb_val - fb_v) ** 2)
                if dist < best_dist:
                    best_dist, best_f = dist, f
        except Exception:
            best_f = max(cmykw, key=cmykw.get)
        return best_f

    grid: list[list[str]] = [['W'] * width for _ in range(height)]

    for row in range(height):
        left_to_right = row % 2 == 0
        cols = range(width) if left_to_right else range(width - 1, -1, -1)

        for col in cols:
            r = max(0.0, min(1.0, tr + err_r[row][col]))
            g = max(0.0, min(1.0, tg + err_g[row][col]))
            b = max(0.0, min(1.0, tb + err_b[row][col]))

            chosen = nearest_filament(r, g, b)
            grid[row][col] = chosen

            fr, fg, fb = FILAMENT_RGB[chosen]
            er, eg, eb = r - fr, g - fg, b - fb

            # Difusão de erro (serpentina bidirecional)
            next_col = col + 1 if left_to_right else col - 1
            if 0 <= next_col < width:
                err_r[row][next_col] += er * 7 / 16
                err_g[row][next_col] += eg * 7 / 16
                err_b[row][next_col] += eb * 7 / 16

            if row + 1 < height:
                prev_col = col - 1 if left_to_right else col + 1
                if 0 <= prev_col < width:
                    err_r[row + 1][prev_col] += er * 3 / 16
                    err_g[row + 1][prev_col] += eg * 3 / 16
                    err_b[row + 1][prev_col] += eb * 3 / 16

                err_r[row + 1][col] += er * 5 / 16
                err_g[row + 1][col] += eg * 5 / 16
                err_b[row + 1][col] += eb * 5 / 16

                if 0 <= next_col < width:
                    err_r[row + 1][next_col] += er * 1 / 16
                    err_g[row + 1][next_col] += eg * 1 / 16
                    err_b[row + 1][next_col] += eb * 1 / 16

    return grid
