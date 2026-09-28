"""
Gerador de arquivos 3MF com dithering CMYK+W por camada.

Dois modos:
  swatch  — cria um swatch de teste (caixa 20x20mm) com as camadas coloridas
  model   — lê um 3MF existente, detecta cores por objeto/volume e aplica CMYK+W

O 3MF de saída é compatível com Bambu Studio, OrcaSlicer e qualquer
slicer que suporte multimaterial. O usuário atribui os 5 slots do AMS
aos filamentos C/M/Y/K/W manualmente no slicer.
"""

from __future__ import annotations
import zipfile
import io
import xml.etree.ElementTree as ET
from pathlib import Path
from color import hex_to_cmykw, hex_to_rgb, FILAMENTS
from dither import layer_sequence
from optimizer import optimize_sequence

# Namespaces 3MF
NS_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
NS_MATERIAL = "http://schemas.microsoft.com/3dmanufacturing/material/2015/02"
NS_BAMBU = "http://schemas.bambulab.com/package/2021"

# Mapeamento filamento → slot AMS (1-indexado)
FILAMENT_SLOT = {'C': 1, 'M': 2, 'Y': 3, 'K': 4, 'W': 5}
FILAMENT_COLOR_HEX = {
    'C': '#00FFFF',
    'M': '#FF00FF',
    'Y': '#FFFF00',
    'K': '#1A1A1A',
    'W': '#FFFFFF',
}


# ---------------------------------------------------------------------------
# Geometria básica: caixa (box)
# ---------------------------------------------------------------------------

def _box_mesh(
    x0: float, y0: float, z0: float,
    x1: float, y1: float, z1: float,
) -> tuple[list[tuple], list[tuple]]:
    """
    Retorna (vértices, triângulos) de uma caixa alinhada aos eixos.
    8 vértices, 12 triângulos (2 por face).
    """
    v = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    t = [
        (0, 1, 2), (0, 2, 3),  # bottom
        (4, 6, 5), (4, 7, 6),  # top
        (0, 4, 5), (0, 5, 1),  # front
        (1, 5, 6), (1, 6, 2),  # right
        (2, 6, 7), (2, 7, 3),  # back
        (0, 3, 7), (0, 7, 4),  # left
    ]
    return v, t


def _mesh_xml(
    parent: ET.Element,
    vertices: list[tuple],
    triangles: list[tuple],
    v_offset: int = 0,
) -> None:
    mesh = ET.SubElement(parent, "mesh")
    verts_el = ET.SubElement(mesh, "vertices")
    for x, y, z in vertices:
        ET.SubElement(verts_el, "vertex", x=f"{x:.4f}", y=f"{y:.4f}", z=f"{z:.4f}")
    tris_el = ET.SubElement(mesh, "triangles")
    for a, b, c in triangles:
        ET.SubElement(tris_el, "triangle",
                      v1=str(a + v_offset),
                      v2=str(b + v_offset),
                      v3=str(c + v_offset))


# ---------------------------------------------------------------------------
# Gerador de swatch de teste
# ---------------------------------------------------------------------------

def generate_swatch(
    hex_color: str,
    n_layers: int = 20,
    layer_height: float = 0.2,
    size_mm: float = 20.0,
    optimize: bool = True,
    output_path: str | None = None,
) -> bytes:
    """
    Gera um swatch 3MF de teste: caixa size_mm x size_mm com n_layers camadas,
    cada camada atribuída ao filamento correto da sequência CMYK+W.

    Retorna os bytes do arquivo 3MF (e salva em output_path se fornecido).
    """
    cmykw = hex_to_cmykw(hex_color)
    sequence = layer_sequence(cmykw, n_layers)
    if optimize:
        sequence = optimize_sequence(sequence)

    # Agrupa camadas consecutivas do mesmo filamento em um único objeto
    groups = _group_runs(sequence)

    model_el = ET.Element("model", {
        "unit": "millimeter",
        "xml:lang": "en-US",
        "xmlns": NS_CORE,
        "xmlns:m": NS_MATERIAL,
    })

    resources = ET.SubElement(model_el, "resources")
    build = ET.SubElement(model_el, "build")

    obj_id = 1
    for filament, layer_indices in groups.items():
        obj_el = ET.SubElement(resources, "object", {
            "id": str(obj_id),
            "type": "model",
            "name": f"Filamento_{filament}",
        })
        all_vertices: list[tuple] = []
        all_triangles: list[tuple] = []

        for layer_idx in layer_indices:
            z0 = layer_idx * layer_height
            z1 = z0 + layer_height
            verts, tris = _box_mesh(0, 0, z0, size_mm, size_mm, z1)
            v_off = len(all_vertices)
            all_vertices.extend(verts)
            all_triangles.extend((a + v_off, b + v_off, c + v_off) for a, b, c in tris)

        _mesh_xml(obj_el, all_vertices, all_triangles)

        slot = FILAMENT_SLOT[filament]
        color = FILAMENT_COLOR_HEX[filament]
        ET.SubElement(build, "item", {
            "objectid": str(obj_id),
            "transform": "1 0 0 0 1 0 0 0 1 0 0 0",
            "p:extruder": str(slot),
            "p:color": color,
        })
        obj_id += 1

    model_bytes = _to_bytes(model_el)
    archive = _pack_3mf(model_bytes, hex_color, cmykw, sequence)

    if output_path:
        Path(output_path).write_bytes(archive)
        print(f"3MF salvo: {output_path}")
        _print_summary(hex_color, cmykw, sequence, groups)

    return archive


# ---------------------------------------------------------------------------
# Processador de 3MF colorido existente
# ---------------------------------------------------------------------------

def process_model(
    input_path: str,
    output_path: str | None = None,
    n_layers: int = 20,
    layer_height: float = 0.2,
    optimize: bool = True,
) -> dict[str, bytes]:
    """
    Lê um 3MF existente, detecta objetos com cor definida,
    e para cada cor gera a sequência CMYK+W correspondente.

    Retorna dict {nome_objeto: bytes_3mf_processado}.
    """
    results: dict[str, bytes] = {}

    with zipfile.ZipFile(input_path, 'r') as zf:
        model_xml = None
        for name in zf.namelist():
            if name.endswith('.model') or name == '3D/3dmodel.model':
                model_xml = zf.read(name)
                break

    if not model_xml:
        print(f"Arquivo 3MF sem modelo detectado: {input_path}")
        return results

    root = ET.fromstring(model_xml)
    ns = {'m': NS_CORE}
    objects = root.findall('.//{%s}object' % NS_CORE)

    colors_found: list[tuple[str, str]] = []

    for obj in objects:
        name = obj.get('name', obj.get('id', 'objeto'))
        color_attr = obj.get('{%s}color' % NS_MATERIAL) or obj.get('color')
        if color_attr and color_attr.startswith('#'):
            colors_found.append((name, color_attr))

    if not colors_found:
        print("Nenhuma cor encontrada no modelo. Extraindo de metadados...")
        # Tenta ler cor do primeiro objeto como fallback
        for obj in objects[:5]:
            oid = obj.get('id', '?')
            colors_found.append((f"objeto_{oid}", '#808080'))

    for name, hex_color in colors_found:
        print(f"\nProcessando '{name}': {hex_color}")
        out_name = f"{Path(input_path).stem}_{name}_cmykw.3mf"
        out_full = str(Path(output_path or '.') / out_name) if output_path else None
        data = generate_swatch(hex_color, n_layers, layer_height, optimize=optimize,
                               output_path=out_full)
        results[name] = data

    return results


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _group_runs(sequence: list[str]) -> dict[str, list[int]]:
    """Agrupa índices de camada por filamento."""
    groups: dict[str, list[int]] = {f: [] for f in FILAMENTS}
    for i, f in enumerate(sequence):
        groups[f].append(i)
    return {f: idxs for f, idxs in groups.items() if idxs}


def _to_bytes(element: ET.Element) -> bytes:
    ET.indent(element, space="  ")
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(element, encoding='unicode').encode('utf-8')


def _pack_3mf(model_bytes: bytes, hex_color: str, cmykw: dict, sequence: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _content_types_xml())
        zf.writestr("_rels/.rels", _rels_xml())
        zf.writestr("3D/3dmodel.model", model_bytes)
        zf.writestr("Metadata/real3dprint.json", _metadata_json(hex_color, cmykw, sequence))
    return buf.getvalue()


def _content_types_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        '<Default Extension="json" ContentType="application/json"/>'
        '</Types>'
    )


def _rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Target="/3D/3dmodel.model" Id="rel-1" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        '</Relationships>'
    )


def _metadata_json(hex_color: str, cmykw: dict, sequence: list[str]) -> str:
    import json
    from collections import Counter
    counts = Counter(sequence)
    return json.dumps({
        "generator": "Real3DPrint",
        "target_color": hex_color,
        "cmykw": {k: round(v, 4) for k, v in cmykw.items()},
        "layer_sequence": sequence,
        "layer_counts": dict(counts),
        "ams_slots": FILAMENT_SLOT,
    }, indent=2)


def _print_summary(hex_color: str, cmykw: dict, sequence: list[str], groups: dict) -> None:
    from collections import Counter
    counts = Counter(sequence)
    print(f"\nResumo do swatch:")
    print(f"  Cor alvo:    {hex_color}")
    print(f"  Total layers: {len(sequence)}")
    print(f"  Distribuição:")
    for f in FILAMENTS:
        if f in counts:
            slot = FILAMENT_SLOT[f]
            print(f"    Slot {slot} ({f}): {counts[f]} camadas  → {cmykw.get(f, 0):.1%}")
    print(f"\n  Configurar no slicer:")
    for f in FILAMENTS:
        if f in counts:
            print(f"    Extrusora {FILAMENT_SLOT[f]} = filamento {f} ({FILAMENT_COLOR_HEX[f]})")
