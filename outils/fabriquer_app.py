"""Fabrique l'application macOS qui ouvre les réglages sans passer par le terminal.

    uv run outils/fabriquer_app.py                    app liée au projet, pour développer
    uv run outils/fabriquer_app.py --autonome         app portable, à installer partout
    uv run outils/fabriquer_app.py --paquet ~/Desktop app portable, plus son archive

L'app n'est pas versionnée, elle se refabrique : un bundle est un dossier d'octets
qui n'a rien à faire dans un dépôt.

**Deux applications, une seule commande.** Elles se ressemblent à l'écran et ne
se ressemblent pas du tout dedans.

- **Liée** (défaut) : un lanceur de quelques kilo-octets qui appelle `uv` sur ce
  dossier de projet. Elle ne marche que sur cette machine, et c'est sa qualité en
  développement : le code qu'elle exécute est celui qu'on vient d'éditer.
- **Autonome** (`--autonome`) : l'interpréteur, les paquets et le modèle Vosk
  voyagent dans le bundle. Environ 170 Mo, aucune dépendance sur la machine
  d'accueil, pas même Python. C'est celle qui se donne à un collègue.

**Ce que l'app change, au-delà du confort.** L'autorisation Accessibilité est
accordée par macOS au sujet qui lance la chaîne. Tant que c'était un terminal,
elle tenait à ce terminal-là ; avec l'app, elle s'accorde une fois à « Contrôle
vocal » et ne bouge plus. À cocher dans Réglages système, Confidentialité et
sécurité, Accessibilité, au premier lancement.
"""

from __future__ import annotations

import argparse
import compileall
import platform
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

#: Version de Python embarquée. Celle du projet, `requires-python >= 3.12`.
PYTHON = "3.12"

#: Les deux architectures de Mac encore en service. La valeur donne le nom uv de
#: l'interpréteur et la plateforme de résolution des paquets.
ARCHITECTURES = {
    "arm64": ("aarch64", "aarch64-apple-darwin"),
    "x86_64": ("x86_64", "x86_64-apple-darwin"),
}

#: Tailles réclamées par `iconutil` pour un jeu d'icônes complet.
TAILLES = [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2), (256, 1), (256, 2), (512, 1), (512, 2)]

SOURCE_LANCEUR = Path(__file__).resolve().parent / "lanceur.c"

LISEZ_MOI = """Contrôle vocal, télécommande vocale pour présentations
=====================================================

Installation, trois gestes.

1. Glisser « {nom}.app » dans le dossier Applications.

2. Lever la mise en quarantaine. macOS marque tout fichier venu d'ailleurs et
   refuse d'ouvrir une application qui n'est pas signée par un développeur
   inscrit chez Apple. Ouvrir Terminal (Applications, Utilitaires) et coller
   cette ligne, puis Entrée :

xattr -dr com.apple.quarantine "/Applications/{nom}.app"

   Sans cette ligne, le double-clic répond que l'application est endommagée.
   Elle ne l'est pas : macOS dit cela de toute application non signée par un
   compte payant, et c'est le cas de celle-ci, distribuée de la main à la main.

3. Double-cliquer sur l'application. Une page de réglages s'ouvre dans le
   navigateur. Elle demande deux autorisations, à accorder dans Réglages
   système, Confidentialité et sécurité :

   - Accessibilité, pour envoyer les touches à l'application projetée. Sans
     elle, l'outil écoute et ne fait rien.
   - Micro, demandé au premier démarrage de l'écoute.

Tout se passe sur la machine : aucun son ne part sur le réseau, et l'outil
fonctionne sans connexion.

Les profils, qui associent des phrases à des touches, s'éditent depuis la page
de réglages. Ils sont rangés dans votre dossier personnel, ici :

~/Library/Application Support/{nom}/profils/

Une mise à jour de l'application ne les touche pas.
"""


def trouver_uv() -> str:
    chemin = shutil.which("uv")
    if chemin:
        return chemin
    for candidat in ("/opt/homebrew/bin/uv", "/usr/local/bin/uv", str(Path.home() / ".local/bin/uv")):
        if Path(candidat).is_file():
            return candidat
    raise SystemExit("uv est introuvable : impossible de fabriquer l'application.")


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
    """Compile `lanceur.c`, en y figeant les chemins qui servent à l'app liée.

    Un binaire plutôt qu'un script : macOS n'accorde pas d'autorisation à un
    script, le processus qui tourne étant alors `/bin/bash`. Sans exécutable
    compilé, l'application n'a pas d'identité et n'apparaît pas dans le panneau
    Accessibilité, quoi qu'elle demande.

    Compilé pour les deux architectures : il ne pèse rien, et une app dont le
    lanceur ne tourne pas sur la machine d'accueil ne montrerait même pas de quoi
    elle est morte.
    """
    commande = [
        "clang",
        "-O2",
        "-Wall",
        "-arch", "arm64",
        "-arch", "x86_64",
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


# -- pièces de l'application autonome --------------------------------------


def interprete_standalone(arch: str) -> Path:
    """Le Python déplaçable que `uv` sait installer, dans l'architecture voulue.

    Celui d'une installation Homebrew ou du système ne convient pas : il porte
    des chemins absolus vers l'endroit où il a été construit, et se tairait au
    premier déplacement. Ceux d'uv sont bâtis pour voyager, on l'a vérifié en
    déplaçant une copie garnie de ses paquets.
    """
    nom_uv, _ = ARCHITECTURES[arch]
    demande = f"cpython-{PYTHON}-macos-{nom_uv}"
    uv = trouver_uv()
    subprocess.run([uv, "python", "install", demande], check=True, capture_output=True)

    racine = Path(
        subprocess.run(
            [uv, "python", "dir"], check=True, capture_output=True, text=True
        ).stdout.strip()
    )
    candidats = sorted(racine.glob(f"cpython-{PYTHON}.*-macos-{nom_uv}-*"))
    if not candidats:
        raise SystemExit(f"Python {PYTHON} pour {arch} introuvable après installation.")
    return candidats[-1]


def embarquer_python(ressources: Path, arch: str) -> Path:
    """Copie l'interpréteur dans le bundle et y installe le projet.

    Les paquets sont posés par `--target` dans le `site-packages` de la copie,
    sans jamais exécuter l'interpréteur cible : c'est ce qui permet de fabriquer
    depuis un Mac Apple Silicon une application pour un Mac Intel, qui autrement
    demanderait Rosetta rien que pour interroger son propre Python.
    """
    source = interprete_standalone(arch)
    destination = ressources / "python"
    print(f"  interpréteur {source.name}")
    shutil.copytree(source, destination, symlinks=True)

    paquets = destination / "lib" / f"python{PYTHON}" / "site-packages"
    _, plateforme = ARCHITECTURES[arch]
    subprocess.run(
        [
            trouver_uv(), "pip", "install",
            "--python-platform", plateforme,
            "--python-version", PYTHON,
            "--target", str(paquets),
            str(PROJET),
        ],
        check=True,
        capture_output=True,
    )
    return destination


def precompiler(python_dir: Path) -> None:
    """Compile les `.pyc` avant la signature, et c'est loin d'être un détail.

    Python écrit ses fichiers compilés à côté des sources, au premier import.
    Dans un bundle signé, cette écriture casserait le sceau qui couvre les
    ressources, donc l'identité de l'application, donc son autorisation
    Accessibilité, en pleine séance et sans rien dire. Les fichiers sont donc
    écrits ici, une fois pour toutes, et le lanceur interdit d'en écrire d'autres.
    """
    compileall.compile_dir(str(python_dir / "lib"), quiet=2, force=True)


def embarquer_donnees(ressources: Path) -> None:
    """Modèle Vosk et profils d'origine, les deux choses que l'app doit trouver
    chez elle. Les profils sont copiés comme gabarits : au premier lancement, le
    module `chemins` les recopie dans le dossier de données de l'utilisateur,
    seul endroit où l'outil ait le droit d'écrire."""
    modeles = sorted((PROJET / "modeles").glob("vosk-model-*"))
    if not modeles:
        raise SystemExit(
            "Aucun modèle Vosk dans modeles/ : une application autonome sans "
            "modèle n'entendrait rien. Voir la commande du README."
        )
    for modele in modeles:
        print(f"  modèle {modele.name}")
        shutil.copytree(modele, ressources / "modeles" / modele.name)

    shutil.copytree(
        PROJET / "profils",
        ressources / "profils",
        ignore=shutil.ignore_patterns("*.py", "__pycache__"),
    )


# -- assemblage ------------------------------------------------------------


def fabriquer(destination: Path, port: int, autonome: bool, arch: str) -> Path:
    app = destination / f"{NOM}.app"
    if app.exists():
        shutil.rmtree(app)

    macos = app / "Contents" / "MacOS"
    ressources = app / "Contents" / "Resources"
    macos.mkdir(parents=True)
    ressources.mkdir(parents=True)

    avec_icone = fabriquer_icone(ressources)
    compiler_lanceur(macos / "lancer", port)

    if autonome:
        python_dir = embarquer_python(ressources, arch)
        embarquer_donnees(ressources)
        precompiler(python_dir)

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

    signer(app, autonome)

    # Le Finder relit la fiche d'une app dont la date de modification a changé.
    subprocess.run(["touch", str(app)], check=False)
    return app


def signer(app: Path, autonome: bool) -> bool:
    """Signature ad hoc, sans certificat de développeur.

    Sans elle, macOS ne peut pas identifier l'application comme titulaire d'une
    autorisation : il retombe sur le binaire réellement exécuté, l'interpréteur
    Python, si bien que l'app n'apparaît jamais dans le panneau Accessibilité et
    que l'autorisation qui la fait marcher tient au chemin d'une version de Python.

    `--deep` parce qu'une app autonome contient des centaines de bibliothèques
    chargées à l'exécution, chacune devant porter sa propre signature. Apple
    déconseille ce raccourci pour une distribution large ; il tient pour une
    signature ad hoc donnée de la main à la main, qui ne prétend à aucune
    garantie d'origine.

    Une identité ad hoc est le condensé du binaire : refabriquer l'application
    en change, et macOS redemande alors l'autorisation Accessibilité. C'est le
    prix de l'absence de certificat, et il se paie à chaque mise à jour.
    """
    commande = ["codesign", "--force", "--sign", "-", "--identifier", IDENTIFIANT]
    if autonome:
        commande.append("--deep")
    try:
        subprocess.run([*commande, str(app)], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as erreur:
        details = getattr(erreur, "stderr", b"") or b""
        print(f"  signature impossible ({details.decode(errors='replace').strip()})")
        print("  l'app marchera, mais son autorisation restera celle de l'interpréteur.")
        return False
    return True


def empaqueter(app: Path, vers: Path) -> Path:
    """Archive livrable, plus la notice qui va avec.

    `ditto` et non `zip` : lui seul conserve les liens symboliques et les
    métadonnées de l'interpréteur embarqué, qu'une archive ordinaire aplatirait,
    et avec eux la signature.
    """
    vers.mkdir(parents=True, exist_ok=True)
    archive = vers / f"{NOM}.zip"
    archive.unlink(missing_ok=True)
    subprocess.run(
        ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(archive)],
        check=True,
    )
    (vers / "LISEZ_MOI.txt").write_text(LISEZ_MOI.format(nom=NOM), encoding="utf-8")
    return archive


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument(
        "--vers", type=Path, default=Path("/Applications"), help="dossier d'installation"
    )
    analyseur.add_argument("--port", type=int, default=8730)
    analyseur.add_argument(
        "--autonome",
        action="store_true",
        help="embarque interpréteur, paquets et modèle : l'app part sur un autre Mac",
    )
    analyseur.add_argument(
        "--arch",
        choices=tuple(ARCHITECTURES),
        default=platform.machine(),
        help="architecture visée (défaut : celle de cette machine)",
    )
    analyseur.add_argument(
        "--paquet",
        type=Path,
        metavar="DOSSIER",
        help="produit aussi une archive livrable et sa notice (implique --autonome)",
    )
    options = analyseur.parse_args()

    autonome = options.autonome or options.paquet is not None
    if not options.vers.is_dir():
        print(f"Dossier introuvable : {options.vers}", file=sys.stderr)
        return 1

    print(f"Fabrication ({'autonome, ' + options.arch if autonome else 'liée au projet'})...")
    try:
        app = fabriquer(options.vers, options.port, autonome, options.arch)
    except PermissionError:
        print(
            f"Écriture refusée dans {options.vers}.\n"
            "Installer ailleurs, par exemple : --vers ~/Applications",
            file=sys.stderr,
        )
        return 1
    except subprocess.CalledProcessError as erreur:
        details = (erreur.stderr or b"").decode(errors="replace").strip()
        print(f"Fabrication échouée :\n{details}", file=sys.stderr)
        return 1

    poids = sum(f.stat().st_size for f in app.rglob("*") if f.is_file()) / 1e6
    print(f"Application fabriquée : {app}  ({poids:.0f} Mo)")

    if options.paquet:
        archive = empaqueter(app, options.paquet)
        print(f"Archive livrable : {archive}")
        print(f"Notice d'installation : {options.paquet / 'LISEZ_MOI.txt'}")

    print(
        "\nAu premier lancement, accorder l'autorisation Accessibilité à "
        f"« {NOM} » :\nRéglages système > Confidentialité et sécurité > Accessibilité."
    )
    if not autonome:
        print(
            "Application liée à ce projet : elle ne marchera pas sur une autre "
            "machine.\nPour une copie qui voyage : --autonome"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
