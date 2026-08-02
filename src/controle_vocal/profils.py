"""Lecture des profils CSV, construction de la grammaire, résolution des phrases.

Un profil associe des formulations parlées à des combinaisons de touches, pour une
application donnée. Le format des colonnes est fixé dans SPECS.md.

Un profil ne porte plus que ce qui dépend de son application. Le mot de réveil, la
pause, la reprise et l'extinction se règlent pour tout l'outil dans `_actions.csv`
(`actions.py`), et un profil qui les déclarerait encore est refusé plutôt
qu'ignoré : une ligne sans effet se découvrirait au pire moment.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from controle_vocal import actions as module_actions
from controle_vocal import tableaux
from controle_vocal.tableaux import Refus, normaliser

COLONNES = ("application", "bundle_id", "commande", "touches", "phrases", "actif")
SEPARATEUR_PHRASES = tableaux.SEPARATEUR_PHRASES
PREFIXE_ACTION_INTERNE = "@"

#: Jeton Vosk qui absorbe tout ce qui n'est pas dans la grammaire.
JETON_INCONNU = "[unk]"

#: Profil traité en premier par la reprise : c'est celui que tout le monde a.
PROFIL_DE_REPLI = "defaut"

__all__ = [
    "COLONNES",
    "Commande",
    "ErreurProfil",
    "Profil",
    "Refus",
    "charger",
    "charger_tous",
    "ecrire",
    "est_actif",
    "lire_lignes",
    "normaliser",
    "profil_pour_bundle",
    "rendre_csv",
    "reprendre_actions",
    "valider",
]


class ErreurProfil(tableaux.ErreurTableau):
    """Profil illisible ou incohérent : colonnes absentes, phrase en double."""


@dataclass(frozen=True)
class Commande:
    """Une ligne du CSV : une action, ses formulations, la touche qu'elle envoie."""

    application: str
    bundle_id: str
    nom: str
    touches: str
    phrases: tuple[str, ...]
    actif: bool

    @property
    def est_action_interne(self) -> bool:
        return self.touches.startswith(PREFIXE_ACTION_INTERNE)

    @property
    def utilisable(self) -> bool:
        """Une commande active dont la touche reste à trouver n'envoie rien : on la
        traite comme inactive plutôt que d'envoyer une frappe vide."""
        return self.actif and bool(self.touches)


def _commandes_internes(jeu: module_actions.Jeu) -> tuple[Commande, ...]:
    """Traduit les actions internes en commandes, pour que la suite de la chaîne
    n'ait qu'un seul type d'objet à connaître.

    Le mot de réveil n'en est pas : il précède les commandes, il n'en est pas une.
    """
    return tuple(
        Commande(
            application="",
            bundle_id="",
            nom=action.nom.removeprefix(PREFIXE_ACTION_INTERNE),
            touches=action.nom,
            phrases=action.phrases,
            actif=True,
        )
        for action in jeu.utilisables
    )


@dataclass(frozen=True)
class Profil:
    """Un fichier CSV chargé en mémoire, prêt à nourrir la grammaire et la décision."""

    nom: str
    chemin: Path
    commandes: tuple[Commande, ...]
    actions: module_actions.Jeu = field(default_factory=module_actions.charger)

    @property
    def application(self) -> str:
        for commande in self.commandes:
            if commande.application:
                return commande.application
        return self.nom

    @property
    def bundle_ids(self) -> frozenset[str]:
        return frozenset(c.bundle_id for c in self.commandes if c.bundle_id)

    @property
    def mots_reveil(self) -> tuple[str, ...]:
        """Formulations acceptées pour le mot de réveil, réglées pour tout l'outil."""
        return self.actions.mots_reveil

    @property
    def commandes_utilisables(self) -> tuple[Commande, ...]:
        """Commandes qui peuvent réellement agir : celles du fichier, plus les
        actions internes communes à tous les profils."""
        return tuple(c for c in self.commandes if c.utilisable) + _commandes_internes(
            self.actions
        )

    def phrases_acceptees(self) -> tuple[str, ...]:
        """Toutes les formulations de commande reconnues, dans l'ordre du fichier."""
        return tuple(
            phrase for c in self.commandes_utilisables for phrase in c.phrases
        )

    def resoudre(self, phrase: str) -> Commande | None:
        """Rend la commande correspondant à une formulation, ou rien si elle est
        inconnue, inactive ou sans touche."""
        cible = normaliser(phrase)
        for commande in self.commandes_utilisables:
            if cible in commande.phrases:
                return commande
        return None

    def grammaire(self) -> list[str]:
        """Grammaire fermée pour Vosk : les énoncés complets attendus, mot de réveil
        collé à la commande, plus le jeton qui absorbe le reste.

        Fournir les énoncés entiers plutôt que des mots isolés oriente le modèle vers
        le motif attendu ; la vérification stricte du motif reste faite à la décision.
        """
        enonces = [
            f"{reveil} {phrase}"
            for reveil in self.mots_reveil
            for phrase in self.phrases_acceptees()
        ]
        return sorted(dict.fromkeys(enonces)) + [JETON_INCONNU]


def charger(chemin: str | Path, jeu: module_actions.Jeu | None = None) -> Profil:
    """Charge un profil depuis son CSV. Le nom du profil est celui du fichier.

    `jeu` évite de relire le fichier d'actions pour chaque profil ; omis, il est lu
    dans le dossier du profil.
    """
    chemin = Path(chemin)
    try:
        lignes = tableaux.lire_lignes(chemin, COLONNES)
    except tableaux.ErreurTableau as erreur:
        raise ErreurProfil(str(erreur)) from erreur

    if jeu is None:
        jeu = module_actions.charger(module_actions.chemin(chemin.parent))

    commandes: list[Commande] = []
    deja_vues = jeu.phrases_prises()
    for numero, ligne in enumerate(lignes, start=2):
        nom = ligne["commande"].strip()
        if not nom:
            continue

        touches = ligne["touches"].strip()
        if touches.startswith(PREFIXE_ACTION_INTERNE):
            raise ErreurProfil(
                f"{chemin.name} ligne {numero} : « {touches} » se règle pour tout "
                f"l'outil dans {module_actions.FICHIER}, plus profil par profil. "
                "Retirer cette ligne."
            )

        commande = Commande(
            application=ligne["application"].strip(),
            bundle_id=ligne["bundle_id"].strip(),
            nom=nom,
            touches=touches,
            phrases=tableaux.decouper_phrases(ligne["phrases"]),
            actif=tableaux.vrai_faux(ligne["actif"]),
        )
        if commande.utilisable:
            for phrase in commande.phrases:
                if phrase in deja_vues:
                    raise ErreurProfil(
                        f"{chemin.name} ligne {numero} : la phrase « {phrase} » sert "
                        f"déjà à « {deja_vues[phrase]} », le choix serait imprévisible"
                    )
                deja_vues[phrase] = nom
        commandes.append(commande)

    return Profil(
        nom=chemin.stem, chemin=chemin, commandes=tuple(commandes), actions=jeu
    )


def charger_tous(dossier: str | Path) -> dict[str, Profil]:
    """Charge tous les profils d'un dossier, gabarit et fichier d'actions exclus :
    le préfixe `_` marque ce qui n'est pas un profil."""
    dossier = Path(dossier)
    jeu = module_actions.charger(module_actions.chemin(dossier))
    return {
        chemin.stem: charger(chemin, jeu)
        for chemin in sorted(dossier.glob("*.csv"))
        if not chemin.name.startswith("_")
    }


def lire_lignes(chemin: str | Path) -> list[dict[str, str]]:
    """Rend les lignes d'un profil telles qu'elles sont écrites dans le fichier.

    Distinct de `charger`, qui normalise les phrases et rattache les actions
    communes : l'interface de réglages édite le fichier, pas le profil qu'il
    produit, sans quoi elle réécrirait des lignes que personne n'a touchées.
    """
    try:
        return tableaux.lire_lignes(chemin, COLONNES)
    except tableaux.ErreurTableau as erreur:
        raise ErreurProfil(str(erreur)) from erreur


def est_actif(ligne: Mapping[str, str]) -> bool:
    """Lit la colonne `actif` d'une ligne brute, avec la même souplesse que le
    chargement (`oui`, `o`, `vrai`, `1`)."""
    return tableaux.vrai_faux(ligne.get("actif", ""))


def valider(
    lignes: Iterable[Mapping[str, str]],
    verifier_touche: Callable[[str], None] | None = None,
    phrases_reservees: Mapping[str, str] | None = None,
) -> list[Refus]:
    """Rejoue sur des lignes brutes les refus que le chargement et le lancement
    opposeraient, pour qu'un profil accepté ici ne fasse jamais échouer un
    démarrage devant le public.

    `verifier_touche` reçoit une combinaison et lève si elle est inconnue :
    `clavier.analyser` fait l'affaire. Omis, le contrôle des touches est sauté, ce
    qui garde ce module indépendant de macOS.

    `phrases_reservees` associe une formulation déjà prise à ce qui la porte,
    typiquement les actions internes : une commande qui reprendrait « pause »
    rendrait le choix imprévisible. Omis, ce sont les formulations d'origine qui
    servent, c'est-à-dire exactement ce que `charger` voit quand le fichier
    d'actions manque : les deux ne peuvent pas diverger.
    """
    if phrases_reservees is None:
        phrases_reservees = module_actions.charger().phrases_prises()

    refus: list[Refus] = []
    noms_vus: dict[str, int] = {}
    phrases_vues: dict[str, str] = dict(phrases_reservees)

    for numero, ligne in enumerate(lignes, start=2):
        if manquantes := set(COLONNES) - set(ligne):
            refus.append(
                Refus(numero, "", f"colonnes absentes : {sorted(manquantes)}")
            )
            continue

        nom = ligne["commande"].strip()
        touches = ligne["touches"].strip()
        actif = est_actif(ligne)

        if not nom:
            refus.append(
                Refus(numero, "commande", "ligne sans nom de commande : la nommer ou la supprimer")
            )
        elif nom in noms_vus:
            refus.append(
                Refus(
                    numero,
                    "commande",
                    f"« {nom} » est déjà défini ligne {noms_vus[nom]} : "
                    "renommer l'une des deux, la seconde resterait sans effet",
                )
            )
        else:
            noms_vus[nom] = numero

        if touches.startswith(PREFIXE_ACTION_INTERNE):
            refus.append(
                Refus(
                    numero,
                    "touches",
                    f"« {touches} » se règle pour tout l'outil, dans les mots de "
                    "l'outil, plus profil par profil : retirer cette ligne",
                )
            )
        elif touches and actif and verifier_touche is not None:
            try:
                verifier_touche(touches)
            except Exception as erreur:  # noqa: BLE001 - le message vient de clavier
                refus.append(Refus(numero, "touches", str(erreur)))

        # Même périmètre que `charger` : les lignes utilisables seulement, et le
        # même découpage des formulations, pour ne pas refuser ici un fichier
        # qu'il accepterait là-bas.
        if not (actif and touches):
            continue
        for phrase in tableaux.decouper_phrases(ligne["phrases"]):
            if phrase in phrases_vues:
                refus.append(
                    Refus(
                        numero,
                        "phrases",
                        f"« {phrase} » sert déjà à « {phrases_vues[phrase]} » : "
                        "le choix serait imprévisible, en changer une",
                    )
                )
            else:
                phrases_vues[phrase] = nom or touches

    return refus


def rendre_csv(lignes: Iterable[Mapping[str, str]]) -> str:
    """Sérialise des lignes au format du gabarit, colonnes dans l'ordre fixé."""
    return tableaux.rendre_csv(lignes, COLONNES)


def ecrire(chemin: str | Path, lignes: Iterable[Mapping[str, str]]) -> None:
    """Écrit un profil, par fichier temporaire puis renommage."""
    tableaux.ecrire(chemin, lignes, COLONNES)


def _ordre_de_reprise(chemin: Path) -> tuple[int, str]:
    """`defaut.csv` d'abord : c'est le profil que tout le monde a, et le plus
    susceptible de porter les formulations que l'utilisateur a éprouvées."""
    return (0 if chemin.stem == PROFIL_DE_REPLI else 1, chemin.name)


def reprendre_actions(dossier: str | Path) -> bool:
    """Sort les actions internes des profils vers le fichier commun, une fois.

    Écrite pour les dossiers d'avant la séparation : sans elle, un profil déjà
    installé chez l'utilisateur ferait échouer le chargement sur sa ligne `@pause`.
    Rend vrai si quelque chose a bougé.

    Deux précautions. Les formulations viennent des profils et non des valeurs
    d'origine, pour ne pas défaire ce qui a été éprouvé en séance. Et un
    `_actions.csv` déjà réglé n'est pas recouvert : seul celui qui est resté aux
    valeurs d'origine, typiquement celui que l'application vient de copier, cède
    la place à ce que portaient les profils.
    """
    dossier = Path(dossier)
    if not dossier.is_dir():
        return False

    trouvees: dict[str, dict[str, str]] = {}
    a_nettoyer: list[tuple[Path, list[dict[str, str]]]] = []

    for fichier in sorted(dossier.glob("*.csv"), key=_ordre_de_reprise):
        if fichier.name.startswith("_"):
            continue
        try:
            lignes = tableaux.lire_lignes(fichier, COLONNES)
        except tableaux.ErreurTableau:
            continue

        gardees = []
        internes = []
        for ligne in lignes:
            cible = internes if ligne["touches"].strip().startswith(
                PREFIXE_ACTION_INTERNE
            ) else gardees
            cible.append(ligne)
        if not internes:
            continue

        for ligne in internes:
            trouvees.setdefault(ligne["touches"].strip(), ligne)
        a_nettoyer.append((fichier, gardees))

    if not a_nettoyer:
        return False

    cible = module_actions.chemin(dossier)
    deja_regle = cible.exists() and module_actions.lire_lignes(
        cible
    ) != module_actions.defauts()
    if not deja_regle:
        module_actions.ecrire(
            cible,
            [
                {
                    "action": nom,
                    "phrases": trouvees[nom]["phrases"]
                    if nom in trouvees
                    else tableaux.joindre_phrases(defaut),
                    "actif": "oui"
                    if nom in module_actions.TOUJOURS_ACTIVES
                    else trouvees.get(nom, {}).get("actif", "oui"),
                }
                for nom, defaut in module_actions.DEFAUTS.items()
            ],
        )

    for fichier, gardees in a_nettoyer:
        ecrire(fichier, gardees)
    return True


def profil_pour_bundle(
    profils: dict[str, Profil], bundle_id: str, repli: str = PROFIL_DE_REPLI
) -> Profil | None:
    """Choisit le profil de l'application au premier plan, avec repli sur `defaut`.

    Un profil dont le `bundle_id` n'est pas encore relevé n'est jamais détecté :
    il faut l'épingler au lancement.
    """
    for profil in profils.values():
        if bundle_id and bundle_id in profil.bundle_ids:
            return profil
    return profils.get(repli)
