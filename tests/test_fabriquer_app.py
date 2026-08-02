"""Garde-fous sur la fabrication de l'application.

Fabriquer une app autonome prend une minute et 186 Mo : ces tests ne le font pas.
Ils tiennent les deux choses qu'une relecture ne voit pas, la compilation du
lanceur et le contenu de la notice, sur laquelle repose l'installation chez
quelqu'un qui n'a ni le projet ni le terminal ouvert.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJET = Path(__file__).resolve().parents[1]
OUTILS = PROJET / "outils"


def _fabricant():
    """Charge `outils/fabriquer_app.py`, qui n'est pas un module du paquet."""
    sys.path.insert(0, str(OUTILS))
    specification = importlib.util.spec_from_file_location(
        "fabriquer_app", OUTILS / "fabriquer_app.py"
    )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@pytest.mark.skipif(shutil.which("clang") is None, reason="outils Xcode absents")
def test_le_lanceur_compile(tmp_path: Path) -> None:
    """Une faute de C ne se verrait qu'à la fabrication, une minute plus tard,
    et seulement chez qui fabrique."""
    resultat = subprocess.run(
        [
            "clang", "-O2", "-Wall", "-Werror",
            "-arch", "arm64", "-arch", "x86_64",
            '-DPROJET="/un/projet"', '-DCHEMIN_UV="/un/uv"', "-DPORT=8730",
            "-o", str(tmp_path / "lancer"),
            str(OUTILS / "lanceur.c"),
        ],
        capture_output=True,
        text=True,
    )
    assert resultat.returncode == 0, resultat.stderr
    assert (tmp_path / "lancer").exists()


def test_le_lanceur_dit_le_port_au_serveur() -> None:
    """Sans cela, l'app guette une porte pendant que le serveur en ouvre une
    autre, et chaque double-clic lance une instance de plus."""
    source = (OUTILS / "lanceur.c").read_text(encoding="utf-8")
    assert source.count('"--port", port') == 2, "les deux modes de lancement"


def test_la_notice_donne_la_levee_de_quarantaine() -> None:
    """C'est la seule chose qui sépare le destinataire d'une application qui
    s'ouvre : macOS annonce une app « endommagée » tant qu'elle porte la marque."""
    notice = _fabricant().LISEZ_MOI
    assert "xattr -dr com.apple.quarantine" in notice
    assert "Accessibilité" in notice
    assert "Application Support" in notice


def test_les_deux_architectures_de_mac_sont_prevues() -> None:
    fabricant = _fabricant()
    assert set(fabricant.ARCHITECTURES) == {"arm64", "x86_64"}
