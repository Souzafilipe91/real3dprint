"""
Matemática de cor perceptual: conversão RGB → XYZ → LAB e Delta-E 2000.

Delta-E 2000 é a métrica padrão da indústria gráfica para diferença de cor
perceptível ao olho humano. Valores de referência:
  < 1.0  → diferença imperceptível
  1–2    → percebida por observador treinado
  2–3.5  → percebida pelo consumidor médio
  3.5–5  → diferença clara
  > 5    → cores distintas
"""

from __future__ import annotations
import math

# Ponto branco D65 (iluminante padrão sRGB)
_Xn, _Yn, _Zn = 0.95047, 1.00000, 1.08883

# Matriz de conversão sRGB linearizado → XYZ
_M = [
    [0.4124564, 0.3575761, 0.1804375],
    [0.2126729, 0.7151522, 0.0721750],
    [0.0193339, 0.1191920, 0.9503041],
]


def _linearize(c: float) -> float:
    """Desfaz gamma sRGB → RGB linear."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _f_lab(t: float) -> float:
    delta = 6.0 / 29.0
    return t ** (1.0 / 3.0) if t > delta ** 3 else t / (3 * delta ** 2) + 4.0 / 29.0


def rgb_to_lab(r: float, g: float, b: float) -> tuple[float, float, float]:
    """RGB normalizado (0–1) → CIELAB (L*, a*, b*)."""
    rl, gl, bl = _linearize(r), _linearize(g), _linearize(b)

    X = _M[0][0] * rl + _M[0][1] * gl + _M[0][2] * bl
    Y = _M[1][0] * rl + _M[1][1] * gl + _M[1][2] * bl
    Z = _M[2][0] * rl + _M[2][1] * gl + _M[2][2] * bl

    fx = _f_lab(X / _Xn)
    fy = _f_lab(Y / _Yn)
    fz = _f_lab(Z / _Zn)

    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b_val = 200.0 * (fy - fz)

    return L, a, b_val


def delta_e(rgb1: tuple[float, float, float], rgb2: tuple[float, float, float]) -> float:
    """
    Delta-E 2000 entre duas cores RGB (0–1).
    Implementação da fórmula CIE DE2000 (Sharma et al., 2005).
    """
    L1, a1, b1 = rgb_to_lab(*rgb1)
    L2, a2, b2 = rgb_to_lab(*rgb2)

    # Passo 1: C* e h* de cada cor
    C1 = math.sqrt(a1 ** 2 + b1 ** 2)
    C2 = math.sqrt(a2 ** 2 + b2 ** 2)

    C_avg = (C1 + C2) / 2.0
    C_avg7 = C_avg ** 7
    G = 0.5 * (1 - math.sqrt(C_avg7 / (C_avg7 + 25 ** 7)))

    a1p = a1 * (1 + G)
    a2p = a2 * (1 + G)

    C1p = math.sqrt(a1p ** 2 + b1 ** 2)
    C2p = math.sqrt(a2p ** 2 + b2 ** 2)

    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360

    # Passo 2: deltas
    dLp = L2 - L1
    dCp = C2p - C1p

    if C1p * C2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    elif h2p - h1p > 180:
        dhp = h2p - h1p - 360
    else:
        dhp = h2p - h1p + 360

    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp / 2))

    # Passo 3: médias
    Lp_avg = (L1 + L2) / 2.0
    Cp_avg = (C1p + C2p) / 2.0

    if C1p * C2p == 0:
        hp_avg = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hp_avg = (h1p + h2p) / 2.0
    elif h1p + h2p < 360:
        hp_avg = (h1p + h2p + 360) / 2.0
    else:
        hp_avg = (h1p + h2p - 360) / 2.0

    T = (
        1
        - 0.17 * math.cos(math.radians(hp_avg - 30))
        + 0.24 * math.cos(math.radians(2 * hp_avg))
        + 0.32 * math.cos(math.radians(3 * hp_avg + 6))
        - 0.20 * math.cos(math.radians(4 * hp_avg - 63))
    )

    SL = 1 + 0.015 * (Lp_avg - 50) ** 2 / math.sqrt(20 + (Lp_avg - 50) ** 2)
    SC = 1 + 0.045 * Cp_avg
    SH = 1 + 0.015 * Cp_avg * T

    Cp_avg7 = Cp_avg ** 7
    RC = 2 * math.sqrt(Cp_avg7 / (Cp_avg7 + 25 ** 7))
    d_theta = 30 * math.exp(-((hp_avg - 275) / 25) ** 2)
    RT = -math.sin(math.radians(2 * d_theta)) * RC

    de2000 = math.sqrt(
        (dLp / SL) ** 2
        + (dCp / SC) ** 2
        + (dHp / SH) ** 2
        + RT * (dCp / SC) * (dHp / SH)
    )

    return de2000


def color_accuracy_report(
    target_rgb: tuple[float, float, float],
    simulated_rgb: tuple[float, float, float],
) -> dict:
    de = delta_e(target_rgb, simulated_rgb)

    if de < 1.0:
        label = "imperceptível"
    elif de < 2.0:
        label = "percebida por observador treinado"
    elif de < 3.5:
        label = "percebida pelo consumidor médio"
    elif de < 5.0:
        label = "diferença clara"
    else:
        label = "cores distintas"

    return {
        "delta_e": round(de, 3),
        "label": label,
        "target_lab": rgb_to_lab(*target_rgb),
        "simulated_lab": rgb_to_lab(*simulated_rgb),
    }
