"""
Otimização de purga, threshold de troca e gerador de gradiente.
"""

from __future__ import annotations
import math
from color import FILAMENTS, hex_to_cmykw, rgb_to_cmykw
from colormath import rgb_to_lab

# Custo de purga relativo entre filamentos (quanto pigmento precisa ser removido).
# Branco → escuro = alto custo. Claro → claro = baixo custo.
# Matriz [de][para]: valor 0–1 (1 = pior caso).
_PURGE_COST: dict[str, dict[str, float]] = {
    'C': {'C': 0.0, 'M': 0.6, 'Y': 0.6, 'K': 0.9, 'W': 0.4},
    'M': {'C': 0.6, 'M': 0.0, 'Y': 0.6, 'K': 0.9, 'W': 0.4},
    'Y': {'C': 0.6, 'M': 0.6, 'Y': 0.0, 'K': 0.9, 'W': 0.4},
    'K': {'C': 0.7, 'M': 0.7, 'Y': 0.7, 'K': 0.0, 'W': 1.0},
    'W': {'C': 0.3, 'M': 0.3, 'Y': 0.3, 'K': 0.3, 'W': 0.0},
}


# ---------------------------------------------------------------------------
# Purge Optimizer
# ---------------------------------------------------------------------------

def purge_cost(sequence: list[str]) -> float:
    """Calcula o custo total de purga de uma sequência de camadas."""
    total = 0.0
    for i in range(1, len(sequence)):
        if sequence[i] != sequence[i - 1]:
            total += _PURGE_COST[sequence[i - 1]][sequence[i]]
    return total


def optimize_sequence(sequence: list[str]) -> list[str]:
    """
    Reordena a sequência para minimizar o custo de purga.

    Estratégia: agrupa camadas do mesmo filamento em blocos contínuos,
    depois ordena os blocos usando o algoritmo do vizinho mais próximo
    (greedy TSP) no grafo de custos de purga.

    Preserva a contagem exata de cada filamento.
    """
    if not sequence:
        return sequence

    counts: dict[str, int] = {}
    for f in sequence:
        counts[f] = counts.get(f, 0) + 1

    active = [f for f in FILAMENTS if counts.get(f, 0) > 0]
    if len(active) == 1:
        return sequence

    ordered: list[str] = []
    current = min(active, key=lambda f: sum(_PURGE_COST[f].values()))
    remaining = set(active)

    while remaining:
        remaining.discard(current)
        ordered.extend([current] * counts[current])
        if remaining:
            current = min(remaining, key=lambda f: _PURGE_COST[ordered[-1]][f])

    return ordered


def purge_report(original: list[str], optimized: list[str]) -> dict:
    """Compara custo de purga antes e depois da otimização."""
    orig_cost = purge_cost(original)
    opt_cost = purge_cost(optimized)
    orig_switches = sum(1 for i in range(1, len(original)) if original[i] != original[i - 1])
    opt_switches = sum(1 for i in range(1, len(optimized)) if optimized[i] != optimized[i - 1])

    return {
        "original_cost": round(orig_cost, 3),
        "optimized_cost": round(opt_cost, 3),
        "reduction_pct": round((1 - opt_cost / orig_cost) * 100, 1) if orig_cost > 0 else 0.0,
        "original_switches": orig_switches,
        "optimized_switches": opt_switches,
    }


# ---------------------------------------------------------------------------
# Threshold de troca
# ---------------------------------------------------------------------------

def apply_threshold(sequence: list[str], min_run: int = 3) -> list[str]:
    """
    Remove trocas de filamento para blocos menores que min_run camadas.

    Filamentos com blocos < min_run são absorvidos pelo filamento mais
    próximo e mais frequente — troca evitada, pequena perda de precisão.
    """
    if min_run <= 1 or not sequence:
        return sequence

    runs = _to_runs(sequence)
    changed = True
    while changed:
        changed = False
        new_runs: list[tuple[str, int]] = []
        i = 0
        while i < len(runs):
            fil, count = runs[i]
            if count < min_run:
                neighbor = runs[i - 1][0] if i > 0 else (runs[i + 1][0] if i + 1 < len(runs) else fil)
                if new_runs:
                    last_fil, last_count = new_runs[-1]
                    if last_fil == neighbor:
                        new_runs[-1] = (last_fil, last_count + count)
                    else:
                        new_runs.append((neighbor, count))
                else:
                    new_runs.append((neighbor, count))
                changed = True
            else:
                new_runs.append((fil, count))
            i += 1
        runs = new_runs

    return _from_runs(runs)


def _to_runs(seq: list[str]) -> list[tuple[str, int]]:
    if not seq:
        return []
    runs = [(seq[0], 1)]
    for f in seq[1:]:
        if f == runs[-1][0]:
            runs[-1] = (f, runs[-1][1] + 1)
        else:
            runs.append((f, 1))
    return runs


def _from_runs(runs: list[tuple[str, int]]) -> list[str]:
    result: list[str] = []
    for f, count in runs:
        result.extend([f] * count)
    return result


# ---------------------------------------------------------------------------
# Gerador de gradiente
# ---------------------------------------------------------------------------

def gradient_cmykw(
    color_a: str,
    color_b: str,
    steps: int,
    perceptual: bool = True,
) -> list[dict[str, float]]:
    """
    Gera uma sequência de 'steps' proporções CMYKW interpolando
    entre color_a e color_b (formato #RRGGBB).

    perceptual=True: interpola no espaço LAB (mais uniforme visualmente).
    perceptual=False: interpola diretamente em RGB (mais rápido).
    """
    from color import hex_to_rgb

    ra, ga, ba = hex_to_rgb(color_a)
    rb, gb, bb = hex_to_rgb(color_b)

    result: list[dict[str, float]] = []

    for i in range(steps):
        t = i / max(steps - 1, 1)

        if perceptual:
            La, aa, ba_lab = rgb_to_lab(ra, ga, ba)
            Lb, ab, bb_lab = rgb_to_lab(rb, gb, bb)
            L = La + t * (Lb - La)
            a = aa + t * (ab - aa)
            b_val = ba_lab + t * (bb_lab - ba_lab)
            r, g, b = _lab_to_rgb(L, a, b_val)
        else:
            r = ra + t * (rb - ra)
            g = ga + t * (gb - ga)
            b = ba + t * (bb - ba)

        result.append(rgb_to_cmykw(
            max(0.0, min(1.0, r)),
            max(0.0, min(1.0, g)),
            max(0.0, min(1.0, b)),
        ))

    return result


def _lab_to_rgb(L: float, a: float, b: float) -> tuple[float, float, float]:
    """CIELAB → RGB (aproximação inversa)."""
    _Xn, _Yn, _Zn = 0.95047, 1.00000, 1.08883

    fy = (L + 16) / 116
    fx = a / 500 + fy
    fz = fy - b / 200

    def finv(t: float) -> float:
        return t ** 3 if t > 6 / 29 else 3 * (6 / 29) ** 2 * (t - 4 / 29)

    X = finv(fx) * _Xn
    Y = finv(fy) * _Yn
    Z = finv(fz) * _Zn

    r_lin =  3.2404542 * X - 1.5371385 * Y - 0.4985314 * Z
    g_lin = -0.9692660 * X + 1.8760108 * Y + 0.0415560 * Z
    b_lin =  0.0556434 * X - 0.2040259 * Y + 1.0572252 * Z

    def gamma(c: float) -> float:
        c = max(0.0, c)
        return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055

    return gamma(r_lin), gamma(g_lin), gamma(b_lin)


# ---------------------------------------------------------------------------
# Modo 4 filamentos (sem branco — Kobra S1 e similares)
# ---------------------------------------------------------------------------

def to_4_filament(cmykw: dict[str, float]) -> dict[str, float]:
    """
    Remove o canal W e redistribui sua proporção para simular cores claras
    sem filamento branco. Estratégia: cores claras ficam mais saturadas;
    cores escuras não são afetadas (W = 0 para elas).

    Limitação conhecida: rosa claro vira magenta, azul claro vira ciano —
    a precisão de cor é menor que no modo 5 filamentos.
    """
    w = cmykw.get('W', 0.0)
    if w < 0.001:
        result = {f: cmykw[f] for f in ('C', 'M', 'Y', 'K')}
        total = sum(result.values())
        return {f: (v / total if total > 0 else 0.25) for f, v in result.items()}

    result = {f: cmykw[f] for f in ('C', 'M', 'Y', 'K')}
    total_cmyk = sum(result.values())

    if total_cmyk < 1e-9:
        # Cor pura branca → sem filamento equivalente; usa o mais claro disponível
        return {'C': 0.0, 'M': 0.0, 'Y': 0.25, 'K': 0.0}

    # Redistribui W proporcionalmente aos canais já presentes
    for f in result:
        result[f] += w * (result[f] / total_cmyk)

    total = sum(result.values())
    return {f: v / total for f, v in result.items()}
