"""Identification de l'application au premier plan, pour choisir le profil actif.

Limite structurelle : dans un navigateur, l'identifiant est celui du navigateur, pas
celui du site. Un Canva ouvert en onglet se rattache donc au profil du navigateur.

Relevé des identifiants, à faire une fois pour remplir la colonne `bundle_id` des CSV :

    uv run -m controle_vocal.application --observer
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

from AppKit import NSWorkspace

#: Rythme d'interrogation du mode observation, en secondes.
PERIODE_OBSERVATION = 0.5


@dataclass(frozen=True)
class ApplicationActive:
    """Ce que le système dit de l'application au premier plan."""

    bundle_id: str
    nom: str

    def __str__(self) -> str:
        return f"{self.nom} ({self.bundle_id or 'sans identifiant'})"


def au_premier_plan() -> ApplicationActive | None:
    """Rend l'application active, ou rien si le système n'en signale aucune."""
    application = NSWorkspace.sharedWorkspace().frontmostApplication()
    if application is None:
        return None
    return ApplicationActive(
        bundle_id=str(application.bundleIdentifier() or ""),
        nom=str(application.localizedName() or ""),
    )


def observer(periode: float = PERIODE_OBSERVATION) -> None:
    """Affiche l'application au premier plan à chaque changement, jusqu'à Ctrl+C."""
    print("Observation en cours, Ctrl+C pour arrêter. Basculez d'une fenêtre à l'autre.")
    precedente: ApplicationActive | None = None
    try:
        while True:
            courante = au_premier_plan()
            if courante != precedente:
                print(f"  {courante if courante else 'aucune application au premier plan'}")
                precedente = courante
            time.sleep(periode)
    except KeyboardInterrupt:
        print("\nObservation arrêtée.")


def _cli(arguments: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(
        prog="controle_vocal.application",
        description="Affiche l'application au premier plan.",
    )
    analyseur.add_argument(
        "--observer",
        action="store_true",
        help="suit les changements en continu, pour relever les identifiants",
    )
    analyseur.add_argument(
        "--periode",
        type=float,
        default=PERIODE_OBSERVATION,
        metavar="SECONDES",
        help="rythme d'interrogation en mode observation",
    )
    options = analyseur.parse_args(arguments)

    if options.observer:
        observer(options.periode)
        return 0

    courante = au_premier_plan()
    print(courante if courante else "aucune application au premier plan")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
