"""
Calibração de filamento — o mais complexo do sistema.

Problema: filamentos reais não são CMYKW ideais. Um ciano medido pode ser
(R=18, G=172, B=204) em vez de (R=0, G=255, B=255). Sem calibração, as
cores impressas divergem sistematicamente do alvo.

Solução: o usuário imprime 5 swatches de calibração (um por filamento) e
mede os RGB resultantes. O algoritmo constrói um perfil que, dado qualquer
cor alvo, resolve as proporções CMYKW que melhor reproduzem aquela cor
usando os filamentos reais — problema de mínimos quadrados não-negativo (NNLS).
"""

from __future__ import annotations
import json
import math
from pathlib import Path
import numpy as np
from numpy.linalg import lstsq
from color import FILAMENTS, FILAMENT_RGB

IDEAL_PROFILE: dict[str, tuple[float, float, float]] = {f: FILAMENT_RGB[f] for f in FILAMENTS}


class FilamentProfile:
    """Perfil de cores medidas dos filamentos reais."""

    def __init__(self, measured: dict[str, tuple[float, float, float]] | None = None):
        self.measured = measured or dict(IDEAL_PROFILE)

    # ------------------------------------------------------------------
    # Persistência
    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> None:
        data = {f: list(rgb) for f, rgb in self.measured.items()}
        Path(path).write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "FilamentProfile":
        data = json.loads(Path(path).read_text())
        return cls({f: tuple(v) for f, v in data.items()})

    # ------------------------------------------------------------------
    # Calibração
    # ------------------------------------------------------------------

    def calibrate(self, target_rgb: tuple[float, float, float]) -> dict[str, float]:
        """
        Encontra as proporções CMYKW que melhor reproduzem target_rgb
        usando os filamentos reais (NNLS — mínimos quadrados não-negativos).

        Modelo: cor_impressa ≈ sum(p_i × cor_real_filamento_i)
        Restrições: p_i >= 0, sum(p_i) = 1

        Retorna proporções normalizadas que somam 1.0.
        """
        # Matriz A (3×5): cada coluna = RGB de um filamento real
        A = np.array([[self.measured[f][ch] for f in FILAMENTS] for ch in range(3)], dtype=float)
        t = np.array(target_rgb, dtype=float)

        # Resolve NNLS iterativamente (projected gradient descent)
        p = self._nnls_simplex(A, t)

        total = p.sum()
        if total < 1e-9:
            p = np.ones(len(FILAMENTS)) / len(FILAMENTS)
        else:
            p = p / total

        return {f: float(p[i]) for i, f in enumerate(FILAMENTS)}

    def _nnls_simplex(self, A: np.ndarray, t: np.ndarray, iterations: int = 500) -> np.ndarray:
        """
        Projected gradient descent: minimiza ||A·p - t||²
        com p >= 0 e sum(p) = 1.
        """
        n = A.shape[1]
        p = np.ones(n) / n
        AtA = A.T @ A
        Att = A.T @ t

        lr = 0.5 / (np.linalg.norm(AtA) + 1e-8)

        for _ in range(iterations):
            grad = AtA @ p - Att
            p = p - lr * grad
            # Projeção no simplex (p >= 0, sum = 1)
            p = self._project_simplex(p)

        return p

    @staticmethod
    def _project_simplex(v: np.ndarray) -> np.ndarray:
        """Projeta vetor v no simplex padrão: p >= 0, sum(p) = 1."""
        n = len(v)
        u = np.sort(v)[::-1]
        cssv = np.cumsum(u)
        rho = np.nonzero(u * np.arange(1, n + 1) > (cssv - 1))[0][-1]
        theta = (cssv[rho] - 1.0) / (rho + 1.0)
        return np.maximum(v - theta, 0.0)

    # ------------------------------------------------------------------
    # Diagnóstico
    # ------------------------------------------------------------------

    def deviation(self) -> dict[str, float]:
        """
        Delta-E entre cada filamento real e seu ideal.
        Quanto maior, mais impreciso o filamento — útil para
        o usuário saber quais filamentos precisam de calibração urgente.
        """
        from colormath import delta_e
        deviations = {}
        for f in FILAMENTS:
            ideal = IDEAL_PROFILE[f]
            real = self.measured[f]
            deviations[f] = delta_e(ideal, real)
        return deviations

    def print_report(self) -> None:
        print("\nRelatório de calibração:")
        print(f"{'Fil':>4}  {'Ideal RGB':>20}  {'Real RGB':>20}  {'Delta-E':>8}")
        print("  " + "-" * 58)
        try:
            devs = self.deviation()
        except Exception:
            devs = {f: float('nan') for f in FILAMENTS}

        for f in FILAMENTS:
            ideal = IDEAL_PROFILE[f]
            real = self.measured[f]
            i_str = f"({ideal[0]:.2f},{ideal[1]:.2f},{ideal[2]:.2f})"
            r_str = f"({real[0]:.2f},{real[1]:.2f},{real[2]:.2f})"
            de = devs[f]
            flag = "  ⚠" if de > 5.0 else ""
            print(f"  {f:>2}  {i_str:>20}  {r_str:>20}  {de:>7.2f}{flag}")


def default_profile() -> FilamentProfile:
    """Perfil padrão (filamentos ideais — sem calibração real)."""
    return FilamentProfile()
