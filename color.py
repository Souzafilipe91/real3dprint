"""
Conversão RGB ↔ CMYK+W para o sistema Real 3D Print.

Lógica subtrativa adaptada para FDM: o branco (W) substitui
o papel branco das impressoras jato de tinta, preenchendo a
cobertura restante após C, M, Y e K.
"""

FILAMENTS = ('C', 'M', 'Y', 'K', 'W')

FILAMENT_RGB = {
    'C': (0.0, 1.0, 1.0),
    'M': (1.0, 0.0, 1.0),
    'Y': (1.0, 1.0, 0.0),
    'K': (0.0, 0.0, 0.0),
    'W': (1.0, 1.0, 1.0),
}


def hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    """#RRGGBB → (r, g, b) normalizados em 0.0–1.0."""
    hex_color = hex_color.lstrip('#')
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    return r, g, b


def rgb_to_cmykw(r: float, g: float, b: float) -> dict[str, float]:
    """
    (r, g, b) em 0.0–1.0 → proporções CMYK+W que somam 1.0.

    Fluxo:
      1. RGB → CMY subtrativo
      2. Extrai K (preto) para reduzir consumo dos outros filamentos
      3. W preenche a cobertura restante (equivale ao papel branco)
      4. Normaliza para soma = 1.0
    """
    c = 1.0 - r
    m = 1.0 - g
    y = 1.0 - b

    k = min(c, m, y)

    if k >= 1.0:
        return {'C': 0.0, 'M': 0.0, 'Y': 0.0, 'K': 1.0, 'W': 0.0}

    c = c - k
    m = m - k
    y = y - k

    # W preenche a cobertura restante: cores escuras (soma > 1) → W=0
    # cores claras (soma < 1) → W = fração de voxels brancos necessária
    w = max(0.0, 1.0 - (c + m + y + k))

    total = c + m + y + k + w
    if total == 0.0:
        return {'C': 0.0, 'M': 0.0, 'Y': 0.0, 'K': 0.0, 'W': 1.0}

    return {
        'C': c / total,
        'M': m / total,
        'Y': y / total,
        'K': k / total,
        'W': w / total,
    }


def hex_to_cmykw(hex_color: str) -> dict[str, float]:
    """Atalho: #RRGGBB → proporções CMYK+W."""
    return rgb_to_cmykw(*hex_to_rgb(hex_color))


def cmykw_to_rgb_preview(cmykw: dict[str, float]) -> tuple[float, float, float]:
    """
    Reconstrói RGB aproximado via mistura óptica aditiva.
    Serve para preview — não representa a cor física exata,
    que depende dos pigmentos reais dos filamentos.
    """
    r = sum(cmykw.get(f, 0.0) * FILAMENT_RGB[f][0] for f in FILAMENTS)
    g = sum(cmykw.get(f, 0.0) * FILAMENT_RGB[f][1] for f in FILAMENTS)
    b = sum(cmykw.get(f, 0.0) * FILAMENT_RGB[f][2] for f in FILAMENTS)
    return (
        max(0.0, min(1.0, r)),
        max(0.0, min(1.0, g)),
        max(0.0, min(1.0, b)),
    )


def describe(cmykw: dict[str, float]) -> str:
    parts = [f"{k}={v:.1%}" for k, v in cmykw.items() if v > 0.001]
    return "  ".join(parts)
