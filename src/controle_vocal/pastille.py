"""Pastille d'état en surimpression sur l'écran projeté : le jalon 2.

Un disque de couleur, sans texte, dans un coin de l'écran. Trois signaux
ponctuels, décidés dans `docs/BRAINSTORMING.md` : entendu, exécuté, incompris.
Le public voit qu'une machine répond, sans lire le détail ; l'état `ignore` du
décideur n'allume rien, sans quoi la pastille clignoterait à chaque bruit de
salle.

S'y ajoutent deux *veilleuses*, d'une autre nature : violettes, pâles, et
permanentes tant que dure l'état qu'elles disent. À taille pleine, l'outil
écoute ; à demi-diamètre, l'écoute est en pause. Une pastille éteinte ne veut
donc plus dire « rien à signaler » mais « outil arrêté », ce qui était la seule
chose que la pastille ne montrait pas : une pause oubliée, où plus rien ne
répond et où rien ne le dit.

Deux pièces séparées, parce qu'une seule des deux se teste sans écran :

- `Pastille` tient le temps, c'est-à-dire quand allumer et quand éteindre.
- une *surface* tient le pixel. `SurfaceCocoa` la dessine pour de vrai,
  `SurfaceMuette` ne fait que noter ce qu'on lui demande.

Banc d'essai, à lancer par-dessus une présentation en plein écran :

    uv run -m controle_vocal.pastille --liste
    uv run -m controle_vocal.pastille --essai
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSColor,
    NSScreen,
    NSView,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
    NSScreenSaverWindowLevel,
    NSStatusWindowLevel,
)
from Foundation import NSDate, NSMakeRect, NSRunLoop
from Quartz import CGShieldingWindowLevel

#: Durée d'allumage d'un signal, en secondes. Assez long pour être vu du fond
#: de la salle, assez court pour ne pas couvrir la commande suivante.
DUREE_SIGNAL = 1.2

#: Diamètre du disque en points, et distance au bord de l'écran.
TAILLE = 36
MARGE = 40

#: Opacité du disque : la pastille se pose sur la diapositive, elle ne la cache pas.
OPACITE = 0.85

#: Ce qui distingue une veilleuse d'un signal ponctuel : une opacité assez basse
#: pour qu'un point fixe sur la projection se remarque quand on le cherche, sans
#: tirer l'œil du public le reste du temps.
OPACITE_VEILLE = 0.35

#: Ce qui distingue les deux veilleuses l'une de l'autre : la pause tient sur un
#: demi-diamètre, l'écoute sur le diamètre plein. Même violet, même pâleur.
PART_EN_PAUSE = 0.5

COINS = ("haut_gauche", "haut_droite", "bas_gauche", "bas_droite")
COIN_PAR_DEFAUT = "bas_droite"

#: Trois niveaux de fenêtre, du plus poli au plus autoritaire. Lequel passe
#: au-dessus d'une application en plein écran se vérifie sur machine, pas sur le
#: papier : d'où l'option `--niveau` du banc d'essai.
NIVEAUX = {
    "statut": NSStatusWindowLevel,
    "economiseur": NSScreenSaverWindowLevel,
    "bouclier": CGShieldingWindowLevel(),
}
NIVEAU_PAR_DEFAUT = "economiseur"

#: Ce qui permet à la fenêtre de suivre la présentation d'un espace à l'autre :
#: elle rejoint tous les bureaux, ne bouge pas avec eux, s'autorise à flotter
#: au-dessus d'un plein écran, et reste hors du cycle de Cmd+²
COMPORTEMENT = (
    NSWindowCollectionBehaviorCanJoinAllSpaces
    | NSWindowCollectionBehaviorStationary
    | NSWindowCollectionBehaviorFullScreenAuxiliary
    | NSWindowCollectionBehaviorIgnoresCycle
)

#: Le temps laissé à AppKit pour dessiner, en secondes. Voir `_pomper`.
RESPIRATION = 0.02


class ErreurPastille(Exception):
    """Pastille impossible à poser : écran demandé absent, réglage inconnu."""


class Signal(str, Enum):
    """Ce que la pastille montre. Les trois premiers sont calés sur le décideur."""

    ENTENDU = "entendu"
    EXECUTE = "execute"
    INCOMPRIS = "incompris"
    ECOUTE = "ecoute"
    PAUSE = "pause"

    @classmethod
    def depuis_etat(cls, etat) -> "Signal | None":
        """Traduit un état de décision en signal, ou rien s'il ne s'en montre aucun.

        Volontairement tenu par la valeur textuelle plutôt que par un import de
        `decision` : la pastille n'a pas à connaître le décideur pour l'afficher.
        Les deux veilleuses n'en sortent jamais, aucun état de décision ne portant
        leur nom : elles viennent de l'état de la séance, pas du verdict rendu sur
        un énoncé.
        """
        valeur = getattr(etat, "value", etat)
        try:
            return cls(valeur)
        except ValueError:
            return None


#: Les trois signaux qui s'allument le temps d'être vus, et les deux fonds qui
#: durent tant que dure l'état de la séance.
SIGNAUX_PONCTUELS = (Signal.ENTENDU, Signal.EXECUTE, Signal.INCOMPRIS)
VEILLEUSES = (Signal.ECOUTE, Signal.PAUSE)

#: Le violet ne dit ni la réussite ni l'échec : il ne ressemble à aucun des trois
#: signaux ponctuels, et c'est ce qui le désigne pour l'état de la séance.
VIOLET = (0.62, 0.45, 0.95)


@dataclass(frozen=True)
class Aspect:
    """L'apparence d'un signal : sa couleur, sa pâleur, sa part du diamètre.

    Une donnée plutôt qu'un branchement dans la surface : les deux veilleuses ne
    diffèrent que par un nombre, et la surface n'a pas à savoir laquelle est
    laquelle pour la dessiner.
    """

    couleur: tuple[float, float, float]
    opacite: float
    part: float = 1.0


ASPECTS: dict[Signal, Aspect] = {
    Signal.ENTENDU: Aspect((0.42, 0.68, 1.00), OPACITE),
    Signal.EXECUTE: Aspect((0.25, 0.82, 0.45), OPACITE),
    Signal.INCOMPRIS: Aspect((0.95, 0.45, 0.20), OPACITE),
    Signal.ECOUTE: Aspect(VIOLET, OPACITE_VEILLE),
    Signal.PAUSE: Aspect(VIOLET, OPACITE_VEILLE, PART_EN_PAUSE),
}


def origine_pastille(
    cadre: tuple[float, float, float, float],
    taille: int = TAILLE,
    coin: str = COIN_PAR_DEFAUT,
    marge: int = MARGE,
) -> tuple[float, float]:
    """Coin bas-gauche de la pastille, dans les coordonnées globales de macOS.

    `cadre` est celui de l'écran visé, `(x, y, largeur, hauteur)`. L'origine est
    en bas à gauche, et celle d'un écran secondaire est décalée par rapport à
    l'écran principal : d'où le calcul à partir de `cadre`, jamais de zéro.
    """
    if coin not in COINS:
        raise ErreurPastille(f"coin inconnu : {coin} (connus : {', '.join(COINS)})")
    x, y, largeur, hauteur = cadre
    gauche = x + marge
    droite = x + largeur - taille - marge
    bas = y + marge
    haut = y + hauteur - taille - marge
    return {
        "haut_gauche": (gauche, haut),
        "haut_droite": (droite, haut),
        "bas_gauche": (gauche, bas),
        "bas_droite": (droite, bas),
    }[coin]


class Surface(Protocol):
    """Ce que la pastille demande à son support d'affichage, et rien de plus."""

    def poser(self, signal: Signal) -> None: ...

    def effacer(self) -> None: ...

    def fermer(self) -> None: ...


class SurfaceMuette:
    """Support qui n'affiche rien et note tout : pastille éteinte, et tests."""

    def __init__(self) -> None:
        self.journal: list[str] = []
        self.signal: Signal | None = None

    def poser(self, signal: Signal) -> None:
        self.signal = signal
        self.journal.append(f"poser:{signal.value}")

    def effacer(self) -> None:
        self.signal = None
        self.journal.append("effacer")

    def fermer(self) -> None:
        self.signal = None
        self.journal.append("fermer")


class SurfaceCocoa:
    """Fenêtre flottante sans bordure, un disque de couleur, sans interaction.

    Trois précautions, chacune contre un défaut précis :

    - politique d'activation « accessoire » : pas d'icône au Dock, et surtout
      aucun vol de focus, qui ferait sortir Canva de sa présentation ;
    - `orderFrontRegardless` plutôt que `makeKeyAndOrderFront` : la fenêtre
      s'affiche sans que le processus devienne l'application active ;
    - le disque est obtenu par le rayon d'angle d'une couche, pas par un dessin
      sur mesure : rien à sous-classer côté Objective-C.

    La fenêtre garde toujours le même cadre, quel que soit le signal : seul le
    disque qu'elle contient maigrit, centré. Redimensionner la fenêtre
    obligerait à recalculer son origine à chaque changement de format, et à
    refaire ce calcul juste pour un écran de projection décalé.
    """

    def __init__(
        self,
        taille: int = TAILLE,
        coin: str = COIN_PAR_DEFAUT,
        ecran: int = 0,
        marge: int = MARGE,
        niveau: str = NIVEAU_PAR_DEFAUT,
    ) -> None:
        if niveau not in NIVEAUX:
            raise ErreurPastille(
                f"niveau inconnu : {niveau} (connus : {', '.join(NIVEAUX)})"
            )
        # Écran et coin sont résolus avant la moindre fenêtre : un réglage
        # fautif doit échouer au lancement, sans rien laisser derrière lui.
        origine = origine_pastille(cadre_ecran(ecran), taille, coin, marge)
        self.taille = taille

        application = NSApplication.sharedApplication()
        application.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        rectangle = NSMakeRect(0, 0, taille, taille)
        self._fenetre = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rectangle, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
        )
        self._fenetre.setOpaque_(False)
        self._fenetre.setBackgroundColor_(NSColor.clearColor())
        self._fenetre.setHasShadow_(False)
        self._fenetre.setIgnoresMouseEvents_(True)
        self._fenetre.setLevel_(NIVEAUX[niveau])
        self._fenetre.setCollectionBehavior_(COMPORTEMENT)

        # Un conteneur transparent occupe la fenêtre, le disque vit dedans :
        # une vue de contenu est étirée d'office au cadre de la fenêtre, une
        # sous-vue garde le format qu'on lui donne.
        self._conteneur = NSView.alloc().initWithFrame_(rectangle)
        self._disque = NSView.alloc().initWithFrame_(rectangle)
        self._disque.setWantsLayer_(True)
        self._disque.layer().setCornerRadius_(taille / 2)
        self._conteneur.addSubview_(self._disque)
        self._fenetre.setContentView_(self._conteneur)

        self._fenetre.setFrameOrigin_(origine)

    def poser(self, signal: Signal) -> None:
        aspect = ASPECTS[signal]
        diametre = self.taille * aspect.part
        retrait = (self.taille - diametre) / 2
        self._disque.setFrame_(NSMakeRect(retrait, retrait, diametre, diametre))
        self._disque.layer().setCornerRadius_(diametre / 2)

        rouge, vert, bleu = aspect.couleur
        couleur = NSColor.colorWithCalibratedRed_green_blue_alpha_(
            rouge, vert, bleu, aspect.opacite
        )
        self._disque.layer().setBackgroundColor_(couleur.CGColor())
        self._fenetre.orderFrontRegardless()
        _pomper()

    def effacer(self) -> None:
        self._fenetre.orderOut_(None)
        _pomper()

    def fermer(self) -> None:
        self._fenetre.orderOut_(None)
        self._fenetre.close()
        _pomper()


def _pomper(duree: float = RESPIRATION) -> None:
    """Laisse tourner la boucle d'exécution le temps qu'AppKit dessine.

    Même piège que dans `application.py` : un processus qui ne fait pas tourner
    sa boucle d'exécution ne voit rien s'afficher, la fenêtre restant en attente
    d'un tour qui ne vient jamais. Vingt millisecondes suffisent, et se perdent
    dans un bloc audio d'un quart de seconde.
    """
    NSRunLoop.currentRunLoop().runUntilDate_(
        NSDate.dateWithTimeIntervalSinceNow_(duree)
    )


def cadre_ecran(index: int = 0) -> tuple[float, float, float, float]:
    """Cadre de l'écran demandé, `(x, y, largeur, hauteur)`.

    L'index 0 est l'écran principal, celui qui porte la barre des menus. En
    projection par recopie il n'y en a qu'un ; en écran étendu, le projecteur
    est un autre index, que `--liste` donne.
    """
    ecrans = NSScreen.screens()
    if not ecrans:
        raise ErreurPastille("aucun écran détecté")
    if not 0 <= index < len(ecrans):
        raise ErreurPastille(
            f"écran {index} inconnu : {len(ecrans)} écran(s) détecté(s), "
            "liste par uv run -m controle_vocal.pastille --liste"
        )
    cadre = ecrans[index].frame()
    return (
        float(cadre.origin.x),
        float(cadre.origin.y),
        float(cadre.size.width),
        float(cadre.size.height),
    )


class Pastille:
    """Le temps de la pastille : allumer sur signal, éteindre à l'échéance.

    Aucune minuterie du système : l'extinction est demandée par `rafraichir`,
    que la boucle principale appelle à chaque bloc audio. Un seul fil, aucun
    verrou, et une logique qui se teste avec une horloge de papier.

    Deux couches se superposent, sans se mélanger : la veilleuse est le fond,
    posée par `veiller` et sans échéance ; un signal ponctuel la couvre le temps
    d'être vu, puis lui rend la place. Le fond n'a donc pas à être reposé par
    l'appelant après chaque commande.
    """

    def __init__(
        self,
        surface: Surface | None = None,
        duree: float = DUREE_SIGNAL,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self.surface: Surface = surface if surface is not None else SurfaceMuette()
        self.duree = duree
        self._horloge = horloge
        self._signal: Signal | None = None
        self._echeance: float | None = None
        self._veilleuse: Signal | None = None

    @property
    def signal(self) -> Signal | None:
        """Le signal ponctuel allumé, veilleuse non comprise."""
        return self._signal

    @property
    def veilleuse(self) -> Signal | None:
        """Le fond permanent, ou rien s'il n'y en a pas."""
        return self._veilleuse

    def signaler(self, signal: Signal | None) -> None:
        """Allume un signal pour la durée réglée. Un `None` n'allume rien."""
        if signal is None:
            return
        self._signal = signal
        self._echeance = self._horloge() + self.duree
        self.surface.poser(signal)

    def veiller(self, veilleuse: Signal | None) -> None:
        """Pose ou retire le fond permanent, sans couper un signal en cours.

        Appelable à chaque tour de boucle : un fond déjà posé ne se redessine
        pas, sans quoi la surface travaillerait pour rien à chaque bloc audio.
        """
        if veilleuse is self._veilleuse:
            return
        self._veilleuse = veilleuse
        if self._signal is None:
            self._montrer_le_fond()

    def rafraichir(self) -> None:
        """Rend la place au fond quand le temps du signal est passé.

        Sans veilleuse, le fond est le noir : la pastille s'éteint.
        """
        if self._echeance is None:
            return
        if self._horloge() >= self._echeance:
            self._signal = None
            self._echeance = None
            self._montrer_le_fond()

    def _montrer_le_fond(self) -> None:
        if self._veilleuse is None:
            self.surface.effacer()
        else:
            self.surface.poser(self._veilleuse)

    def fermer(self) -> None:
        self._signal = None
        self._echeance = None
        self._veilleuse = None
        self.surface.fermer()

    def __enter__(self) -> "Pastille":
        return self

    def __exit__(self, *_exception) -> None:
        self.fermer()


def ouvrir(
    active: bool = True,
    coin: str = COIN_PAR_DEFAUT,
    ecran: int = 0,
    taille: int = TAILLE,
    niveau: str = NIVEAU_PAR_DEFAUT,
    duree: float = DUREE_SIGNAL,
) -> Pastille:
    """Rend une pastille prête à l'emploi, muette si elle est désactivée.

    L'appelant n'a donc jamais à tester si la pastille existe : elle existe
    toujours, et ne fait rien quand on n'en veut pas.
    """
    surface: Surface = (
        SurfaceCocoa(taille=taille, coin=coin, ecran=ecran, niveau=niveau)
        if active
        else SurfaceMuette()
    )
    return Pastille(surface, duree=duree)


def _lister_ecrans() -> None:
    ecrans = NSScreen.screens()
    print(f"{len(ecrans)} écran(s) :")
    for index, ecran in enumerate(ecrans):
        cadre = ecran.frame()
        principal = " (principal, barre des menus)" if index == 0 else ""
        print(
            f"  {index} : {int(cadre.size.width)}×{int(cadre.size.height)} "
            f"en ({int(cadre.origin.x)}, {int(cadre.origin.y)}){principal}"
        )


def essai(pastille: Pastille, tours: int = 3, repos: float = 0.6) -> None:
    """Fait défiler les signaux, pour juger la pastille à l'œil.

    À lancer une présentation ouverte en plein écran : c'est le seul moyen de
    vérifier que la fenêtre passe au-dessus, ce qu'aucun test ne dit.
    """
    print(
        "Trois signaux vont défiler : bleu « entendu », vert « exécuté », "
        "orange « incompris ».\nBasculez sur la présentation en plein écran, "
        "la pastille doit rester visible."
    )
    for tour in range(1, tours + 1):
        for signal in SIGNAUX_PONCTUELS:
            print(f"  tour {tour} : {signal.value}")
            pastille.signaler(signal)
            _attendre(pastille, pastille.duree)
            _attendre(pastille, repos)

    print(
        "  veilleuses violettes, permanentes : disque plein pendant l'écoute,\n"
        "    demi-disque pendant la pause. Une commande va passer par-dessus la\n"
        "    seconde, qui doit reprendre sa place ensuite."
    )
    for veilleuse in VEILLEUSES:
        print(f"    {veilleuse.value}")
        pastille.veiller(veilleuse)
        _attendre(pastille, 3.0)
    pastille.signaler(Signal.EXECUTE)
    _attendre(pastille, pastille.duree + 3.0)
    pastille.veiller(None)
    _attendre(pastille, repos)
    print("Essai terminé.")


def _attendre(pastille: Pastille, duree: float) -> None:
    """Attend en laissant vivre la fenêtre, et en éteignant à l'heure dite."""
    fin = time.monotonic() + duree
    while time.monotonic() < fin:
        pastille.rafraichir()
        _pomper(0.05)


def _cli(arguments: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(
        prog="controle_vocal.pastille",
        description="Pastille d'état en surimpression : banc d'essai.",
    )
    analyseur.add_argument(
        "--liste", action="store_true", help="affiche les écrans et leur index"
    )
    analyseur.add_argument(
        "--essai", action="store_true", help="fait défiler les trois signaux"
    )
    analyseur.add_argument("--coin", choices=COINS, default=COIN_PAR_DEFAUT)
    analyseur.add_argument("--ecran", type=int, default=0, metavar="INDEX")
    analyseur.add_argument("--taille", type=int, default=TAILLE, metavar="POINTS")
    analyseur.add_argument(
        "--niveau",
        choices=tuple(NIVEAUX),
        default=NIVEAU_PAR_DEFAUT,
        help="hauteur de la fenêtre, à changer si elle passe sous le plein écran",
    )
    analyseur.add_argument(
        "--duree", type=float, default=DUREE_SIGNAL, metavar="SECONDES"
    )
    analyseur.add_argument("--tours", type=int, default=3, metavar="N")
    options = analyseur.parse_args(arguments)

    if options.liste:
        _lister_ecrans()
        return 0

    try:
        pastille = ouvrir(
            active=True,
            coin=options.coin,
            ecran=options.ecran,
            taille=options.taille,
            niveau=options.niveau,
            duree=options.duree,
        )
    except ErreurPastille as erreur:
        print(f"Erreur : {erreur}")
        return 2

    with pastille:
        if options.essai:
            essai(pastille, tours=options.tours)
        else:
            print("Pastille verte pendant trois secondes, Ctrl+C pour arrêter.")
            pastille.signaler(Signal.EXECUTE)
            _attendre(pastille, 3.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
