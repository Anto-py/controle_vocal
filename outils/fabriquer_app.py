"""Fabrique l'application macOS qui ouvre les réglages sans passer par le terminal.

    uv run outils/fabriquer_app.py
    uv run outils/fabriquer_app.py --vers ~/Applications

L'app n'est pas versionnée, elle se refabrique : un bundle est un dossier d'octets
qui n'a rien à faire dans un dépôt, et les chemins de la machine y sont inscrits.

**Ce que l'app change, au-delà du confort.** L'autorisation Accessibilité est
accordée par macOS au sujet qui lance la chaîne. Tant que c'était un terminal,
elle tenait à ce terminal-là ; avec l'app, elle s'accorde une fois à « Contrôle
vocal » et ne bouge plus. À cocher dans Réglages système, Confidentialité et
sécurité, Accessibilité, au premier lancement.
"""

from __future__ import annotations

import argparse
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from icone import dessiner  # noqa: E402

PROJET = Path(__file__).resolve().parents[1]
NOM = "Contrôle vocal"
IDENTIFIANT = "fr.antobareau.controle-vocal"

#: Tailles réclamées par `iconutil` pour un jeu d'icônes complet.
TAILLES = [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2), (256, 1), (256, 2), (512, 1), (512, 2)]

SOURCE_LANCEUR = Path(__file__).resolve().parent / "lanceur.c"


def trouver_uv() -> str:
    chemin = shutil.which("uv")
    if chemin:
        return chemin
    for candidat in ("/opt/homebrew/bin/uv", "/usr/local/bin/uv", str(Path.home() / ".local/bin/uv")):
        if Path(candidat).is_file():
            return candidat
    raise SystemExit("uv est introuvable : impossible d'inscrire son chemin dans l'app.")


def fabriquer_icone(ressources: Path) -> bool:
    """Rend vrai si `iconutil` a produit l'icône. Une app sans icône reste
    utilisable, ce n'est pas une raison d'échouer."""
    jeu = ressources / "icone.iconset"
    jeu.mkdir(parents=True, exist_ok=True)
    for taille, facteur in TAILLES:
        suffixe = "@2x" if facteur == 2 else ""
        (jeu / f"icon_{taille}x{taille}{suffixe}.png").write_bytes(dessiner(taille * facteur))

    try:
        subprocess.run(
            ["iconutil", "-c", "icns", str(jeu), "-o", str(ressources / "icone.icns")],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as erreur:
        print(f"  icône non convertie ({erreur}), l'app aura celle du système.")
        return False
    finally:
        shutil.rmtree(jeu, ignore_errors=True)
    return True


def compiler_lanceur(cible: Path, port: int) -> None:
    """Compile `lanceur.c`, en y figeant les chemins de cette machine.

    Un binaire plutôt qu'un script : macOS n'accorde pas d'autorisation à un
    script, le processus qui tourne étant alors `/bin/bash`. Sans exécutable
    compilé, l'application n'a pas d'identité et n'apparaît pas dans le panneau
    Accessibilité, quoi qu'elle demande.
    """
    commande = [
        "clang",
        "-O2",
        "-Wall",
        f'-DPROJET="{PROJET}"',
        f'-DCHEMIN_UV="{trouver_uv()}"',
        f"-DPORT={port}",
        "-o",
        str(cible),
        str(SOURCE_LANCEUR),
    ]
    try:
        subprocess.run(commande, check=True, capture_output=True)
    except FileNotFoundError as erreur:
        raise SystemExit(
            "clang est introuvable. Installer les outils en ligne de commande :\n"
            "  xcode-select --install"
        ) from erreur
    except subprocess.CalledProcessError as erreur:
        raise SystemExit(
            f"Compilation du lanceur échouée :\n{erreur.stderr.decode(errors='replace')}"
        ) from erreur
    cible.chmod(0o755)


def fabriquer(destination: Path, port: int) -> Path:
    app = destination / f"{NOM}.app"
    if app.exists():
        shutil.rmtree(app)

    macos = app / "Contents" / "MacOS"
    ressources = app / "Contents" / "Resources"
    macos.mkdir(parents=True)
    ressources.mkdir(parents=True)

    avec_icone = fabriquer_icone(ressources)

    compiler_lanceur(macos / "lancer", port)

    fiche = {
        "CFBundleName": NOM,
        "CFBundleDisplayName": NOM,
        "CFBundleIdentifier": IDENTIFIANT,
        "CFBundleExecutable": "lancer",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "CFBundleInfoDictionaryVersion": "6.0",
        "NSHighResolutionCapable": True,
        # Le micro est ouvert par l'outil que cette app lance : la demande
        # d'autorisation remonte jusqu'à elle, et macOS exige une explication.
        "NSMicrophoneUsageDescription": (
            "Le micro sert à reconnaître les commandes de la télécommande vocale. "
            "Aucun son ne quitte la machine."
        ),
    }
    if avec_icone:
        fiche["CFBundleIconFile"] = "icone"
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps(fiche))

    signer(app)

    # Le Finder relit la fiche d'une app dont la date de modification a changé.
    subprocess.run(["touch", str(app)], check=False)
    return app


def signer(app: Path) -> bool:
    """Signature ad hoc, sans certificat de développeur.

    Sans elle, macOS ne peut pas identifier l'application comme titulaire d'une
    autorisation : il retombe sur le binaire réellement exécuté, l'interpréteur
    Python, si bien que l'app n'apparaît jamais dans le panneau Accessibilité et
    que l'autorisation qui la fait marcher tient au chemin d'une version de Python.

    Une signature ad hoc suffit à donner une identité stable sur cette machine ;
    elle ne permet pas la distribution, ce qui n'est pas le sujet ici.
    """
    try:
        subprocess.run(
            ["codesign", "--force", "--sign", "-", "--identifier", IDENTIFIANT, str(app)],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as erreur:
        details = getattr(erreur, "stderr", b"") or b""
        print(f"  signature impossible ({details.decode(errors='replace').strip()})")
        print("  l'app marchera, mais son autorisation restera celle de l'interpréteur.")
        return False
    return True


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument(
        "--vers", type=Path, default=Path("/Applications"), help="dossier d'installation"
    )
    analyseur.add_argument("--port", type=int, default=8730)
    options = analyseur.parse_args()

    if not options.vers.is_dir():
        print(f"Dossier introuvable : {options.vers}", file=sys.stderr)
        return 1

    try:
        app = fabriquer(options.vers, options.port)
    except PermissionError:
        print(
            f"Écriture refusée dans {options.vers}.\n"
            "Installer ailleurs, par exemple : --vers ~/Applications",
            file=sys.stderr,
        )
        return 1

    print(f"Application fabriquée : {app}")
    print(
        "\nAu premier lancement, accorder l'autorisation Accessibilité à "
        f"« {NOM} » :\nRéglages système > Confidentialité et sécurité > Accessibilité."
        "\nElle ne dépendra plus d'un terminal."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
