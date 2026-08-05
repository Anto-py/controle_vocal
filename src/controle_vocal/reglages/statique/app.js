/* Interface de réglages : liste des profils à gauche, table des commandes à droite.
 *
 * La page ne valide rien elle-même. Le serveur seul dit oui ou non, avec les
 * mêmes contrôles que le lancement : une page qui aurait sa propre idée de ce
 * qui est valide finirait par diverger du coeur, et c'est le coeur qui a le
 * dernier mot devant le public.
 */

const COLONNES = ["application", "bundle_id", "commande", "touches", "phrases", "actif"];

const etat = {
  profil: null,
  lignes: [],
  touches: { touches: [], modificateurs: [] },
  moteur: { actif: false },
  actions: { lignes: [], libelles: {}, toujours_actives: [] },
};

/* Rythme de relecture de l'état de la télécommande. Deux secondes suffisent :
 * l'interrupteur doit surtout dire la vérité quand l'outil s'est arrêté tout
 * seul, micro débranché ou « extinction » dite à la voix. */
const PERIODE_ETAT = 2000;

const $ = (id) => document.getElementById(id);

// --- Accès au serveur -------------------------------------------------------

async function demander(route, options = {}) {
  const reponse = await fetch(route, options);
  const type = reponse.headers.get("Content-Type") || "";
  const charge = type.includes("json") ? await reponse.json() : await reponse.text();
  return { ok: reponse.ok, code: reponse.status, charge };
}

// --- Rendu ------------------------------------------------------------------

function rendreListeProfils(profils) {
  const liste = $("liste-profils");
  liste.replaceChildren();
  for (const profil of profils) {
    const element = document.createElement("li");
    const bouton = document.createElement("button");
    bouton.type = "button";
    bouton.className = "profil-bouton" + (profil.erreur ? " casse" : "");
    bouton.setAttribute("aria-current", String(profil.nom === etat.profil));

    const nom = document.createElement("span");
    nom.className = "profil-nom";
    nom.textContent = profil.nom;

    const detail = document.createElement("span");
    detail.className = "profil-detail";
    detail.textContent = profil.erreur
      ? "fichier illisible"
      : `${profil.application || "sans nom"} · ${profil.commandes} active${profil.commandes > 1 ? "s" : ""}`;

    bouton.append(nom, detail);
    bouton.addEventListener("click", () => ouvrirProfil(profil.nom));
    element.append(bouton);
    liste.append(element);
  }
}

function champ(ligne, colonne, index, options = {}) {
  const entree = document.createElement("input");
  entree.className = "retro-input";
  entree.type = "text";
  entree.value = ligne[colonne] ?? "";
  entree.dataset.colonne = colonne;
  entree.setAttribute("aria-label", options.etiquette || colonne);
  if (options.liste) entree.setAttribute("list", options.liste);
  if (options.disabled) entree.disabled = true;
  entree.addEventListener("input", () => {
    etat.lignes[index][colonne] = entree.value;
  });
  return entree;
}

function rendreTable() {
  const corps = $("corps-table");
  corps.replaceChildren();

  etat.lignes.forEach((ligne, index) => {
    const interne = (ligne.touches || "").startsWith("@");
    const rangee = document.createElement("tr");
    rangee.className = interne ? "interne" : "";
    rangee.dataset.index = String(index);

    const celluleActif = document.createElement("td");
    const case_ = document.createElement("input");
    case_.type = "checkbox";
    case_.className = "case-actif";
    case_.checked = ["oui", "o", "vrai", "1", "true"].includes(
      (ligne.actif || "").trim().toLowerCase(),
    );
    case_.setAttribute("aria-label", `Activer ${ligne.commande || "cette commande"}`);
    case_.addEventListener("change", () => {
      etat.lignes[index].actif = case_.checked ? "oui" : "non";
    });
    celluleActif.append(case_);

    const celluleNom = document.createElement("td");
    celluleNom.append(champ(ligne, "commande", index, { etiquette: "Nom de la commande" }));

    const celluleTouches = document.createElement("td");
    celluleTouches.append(
      champ(ligne, "touches", index, {
        etiquette: "Touches à envoyer",
        liste: "touches-connues",
      }),
    );

    const cellulePhrases = document.createElement("td");
    cellulePhrases.append(
      champ(ligne, "phrases", index, { etiquette: "Formulations, séparées par |" }),
    );

    const celluleSuppression = document.createElement("td");
    const supprimer = document.createElement("button");
    supprimer.type = "button";
    supprimer.className = "supprimer";
    supprimer.textContent = "✕";
    // Une ligne interne restée d'un ancien profil sera refusée à l'enregistrement :
    // il faut donc pouvoir la supprimer, plus la protéger comme autrefois.
    supprimer.title = interne
      ? "Cette action se règle dans les mots de l'outil : retirer la ligne"
      : "Supprimer la ligne";
    supprimer.setAttribute("aria-label", `Supprimer ${ligne.commande || "la ligne"}`);
    supprimer.addEventListener("click", () => {
      etat.lignes.splice(index, 1);
      rendreTable();
    });
    celluleSuppression.append(supprimer);

    rangee.append(celluleActif, celluleNom, celluleTouches, cellulePhrases, celluleSuppression);
    corps.append(rangee);
  });
}

function rendreTouchesConnues() {
  let liste = document.getElementById("touches-connues");
  if (!liste) {
    liste = document.createElement("datalist");
    liste.id = "touches-connues";
    document.body.append(liste);
  }
  // Les actions internes n'y figurent pas : elles ne s'écrivent plus dans un
  // profil, et les proposer ici mènerait droit à un refus.
  liste.replaceChildren(
    ...etat.touches.touches.map((valeur) => {
      const option = document.createElement("option");
      option.value = valeur;
      return option;
    }),
  );
}

function afficherBandeau(classe, titre, details = [], cible = "bandeau") {
  const bandeau = $(cible);
  bandeau.className = `bandeau ${classe}`;
  bandeau.replaceChildren();

  const paragraphe = document.createElement("p");
  paragraphe.textContent = titre;
  bandeau.append(paragraphe);

  if (details.length) {
    const liste = document.createElement("ul");
    for (const detail of details) {
      const item = document.createElement("li");
      item.textContent = detail;
      liste.append(item);
    }
    bandeau.append(liste);
  }
  bandeau.hidden = false;
}

function marquerRefus(refus) {
  document.querySelectorAll(".fautive").forEach((r) => r.classList.remove("fautive"));
  document.querySelectorAll(".retro-input.error").forEach((c) => c.classList.remove("error"));
  document.querySelectorAll(".refus-ligne").forEach((n) => n.remove());

  for (const r of refus) {
    // La ligne 2 du fichier est la première ligne de données.
    const rangee = document.querySelector(`tr[data-index="${r.ligne - 2}"]`);
    if (!rangee) continue;
    rangee.classList.add("fautive");
    const cellule = rangee.querySelector(`[data-colonne="${r.colonne}"]`);
    if (cellule) {
      cellule.classList.add("error");
      const note = document.createElement("span");
      note.className = "refus-ligne";
      note.textContent = r.message;
      cellule.parentElement.append(note);
    }
  }
}

// --- Les mots de l'outil ----------------------------------------------------

/* Le mot de réveil, la pause, la reprise et l'extinction valent pour tous les
 * profils : ils règlent la télécommande, pas l'application. Ils ont donc leur
 * fichier, leur route, et ce bloc à eux, au lieu d'être noyés dans la table des
 * commandes où rien ne disait qu'on pouvait les changer. */

function champAction(ligne, index) {
  const libelle = etat.actions.libelles[ligne.action] || {};
  const fixe = (etat.actions.toujours_actives || []).includes(ligne.action);

  const bloc = document.createElement("div");
  bloc.className = "champ-action";
  bloc.dataset.index = String(index);

  const etiquette = document.createElement("label");
  etiquette.className = "option";
  const titre = document.createElement("span");
  titre.className = "retro-label";
  titre.textContent = libelle.titre || ligne.action;

  const entree = document.createElement("input");
  entree.className = "retro-input";
  entree.type = "text";
  entree.value = ligne.phrases || "";
  entree.dataset.colonne = "phrases";
  entree.addEventListener("input", () => {
    etat.actions.lignes[index].phrases = entree.value;
  });
  etiquette.append(titre, entree);

  const note = document.createElement("p");
  note.className = "note";
  note.textContent = libelle.detail || "";

  bloc.append(etiquette, note);

  // L'extinction et le mot de réveil ne s'éteignent pas : sans le premier on ne
  // peut plus arrêter l'outil à la voix, sans le second la moindre phrase de
  // cours agirait. Leur case n'est donc pas affichée du tout.
  if (!fixe) {
    const case_ = document.createElement("label");
    case_.className = "option-case";
    const bouton = document.createElement("input");
    bouton.type = "checkbox";
    bouton.className = "case-actif";
    bouton.checked = ["oui", "o", "vrai", "1", "true"].includes(
      (ligne.actif || "").trim().toLowerCase(),
    );
    bouton.addEventListener("change", () => {
      etat.actions.lignes[index].actif = bouton.checked ? "oui" : "non";
    });
    const texte = document.createElement("span");
    texte.textContent = "Active";
    case_.append(bouton, texte);
    bloc.append(case_);
  }

  return bloc;
}

function rendreActions() {
  $("champs-actions").replaceChildren(
    ...etat.actions.lignes.map((ligne, index) => champAction(ligne, index)),
  );
}

function marquerRefusActions(refus) {
  document.querySelectorAll(".champ-action").forEach((bloc) => {
    bloc.classList.remove("fautive");
    bloc.querySelector(".retro-input")?.classList.remove("error");
    bloc.querySelector(".refus-ligne")?.remove();
  });

  for (const r of refus) {
    // La ligne 2 du fichier est la première ligne de données.
    const bloc = document.querySelector(`.champ-action[data-index="${r.ligne - 2}"]`);
    if (!bloc) continue;
    bloc.classList.add("fautive");
    bloc.querySelector(".retro-input")?.classList.add("error");
    const note = document.createElement("span");
    note.className = "refus-ligne";
    note.textContent = r.message;
    bloc.append(note);
  }
}

async function chargerActions() {
  const { ok, charge } = await demander("/api/actions");
  if (!ok) {
    return afficherBandeau(
      "echec",
      "Mots de l'outil illisibles.",
      [charge.erreur || ""],
      "bandeau-actions",
    );
  }
  etat.actions = charge;
  rendreActions();
}

async function enregistrerActions() {
  const bouton = $("enregistrer-actions");
  bouton.disabled = true;
  try {
    const { ok, charge } = await demander("/api/actions", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lignes: etat.actions.lignes }),
    });

    if (ok) {
      marquerRefusActions([]);
      return afficherBandeau(
        "succes",
        "Mots de l'outil enregistrés.",
        ["Redémarrer la télécommande pour qu'elle les entende."],
        "bandeau-actions",
      );
    }

    const refus = charge.refus || [{ ligne: 0, colonne: "", message: charge.erreur }];
    marquerRefusActions(refus);
    afficherBandeau(
      "echec",
      "Rien n'a été écrit, le fichier est intact.",
      refus.map((r) => r.message),
      "bandeau-actions",
    );
  } finally {
    bouton.disabled = false;
  }
}

// --- La télécommande, marche et arrêt ---------------------------------------

function rendreMoteur(moteur) {
  etat.moteur = moteur;
  const bouton = $("interrupteur");
  bouton.setAttribute("aria-pressed", String(moteur.actif));
  bouton.disabled = false;
  bouton.querySelector(".interrupteur-action").textContent = moteur.actif
    ? "Arrêter"
    : "Mettre en marche";

  const detail = [];
  if (moteur.actif) {
    detail.push("en marche");
    if (moteur.options?.profil) detail.push(`profil ${moteur.options.profil}`);
    else detail.push("profil automatique");
    if (moteur.options?.pastille) detail.push("pastille allumée");
  } else if (moteur.code_retour !== null && moteur.code_retour !== undefined) {
    detail.push(moteur.code_retour === 0 ? "arrêtée" : `arrêtée (code ${moteur.code_retour})`);
  } else {
    detail.push("arrêtée");
  }
  $("etat-moteur").textContent = detail.join(" · ");

  $("option-profil").disabled = moteur.actif;
  $("option-pastille").disabled = moteur.actif;

  const journal = $("journal-moteur");
  const lignes = moteur.journal || [];
  journal.hidden = lignes.length === 0;
  journal.textContent = lignes.join("\n");
  journal.scrollTop = journal.scrollHeight;
}

async function relireMoteur() {
  const { ok, charge } = await demander("/api/moteur");
  if (ok) rendreMoteur(charge);
}

async function basculerMoteur() {
  const bouton = $("interrupteur");
  bouton.disabled = true;

  const arret = etat.moteur.actif;
  const options = arret
    ? {}
    : {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          profil: $("option-profil").value || null,
          pastille: $("option-pastille").checked,
        }),
      };
  const route = arret ? "/api/moteur/arreter" : "/api/moteur/demarrer";
  const { ok, charge } = await demander(route, arret ? { method: "POST" } : options);

  if (!ok) {
    afficherBandeau("echec", arret ? "Arrêt impossible." : "Lancement impossible.", [
      charge.erreur || "",
    ]);
    return relireMoteur();
  }
  rendreMoteur(charge);
  $("bandeau").hidden = true;

  // Un échec au lancement (micro absent, modèle manquant) se voit à la seconde
  // suivante, pas à l'instant du clic : le processus a le temps de mourir.
  if (!arret) setTimeout(relireMoteur, 1200);
}

// --- L'autorisation macOS ---------------------------------------------------

/* Elle est affichée en permanence, accordée ou non. Une autorisation qui marche
 * sans que l'application figure dans le panneau des Réglages système est une
 * autorisation empruntée à un autre maillon de la chaîne, qui tombera le jour où
 * celui-ci changera de version. Mieux vaut la voir que la découvrir en séance. */

async function relireAutorisation() {
  const { ok, charge } = await demander("/api/accessibilite");
  const bloc = $("autorisation");
  if (!ok) {
    bloc.hidden = true;
    return;
  }
  bloc.hidden = false;
  bloc.classList.toggle("manquante", !charge.accordee);
  /* La consigne de relance est portée par le bandeau permanent, et pas
   * seulement par celui qui suit la demande : le verdict est figé pour la durée
   * du processus, si bien qu'une autorisation qu'on vient de cocher continue de
   * s'afficher absente. Sans cette phrase, on croit la case sans effet. */
  $("autorisation-texte").textContent = charge.accordee
    ? "Autorisation Accessibilité accordée : les touches peuvent partir."
    : "Autorisation Accessibilité absente : la télécommande démarrera, mais aucune touche ne partira. Si elle vient d'être cochée dans les Réglages système, fermer les réglages par le bouton ci-dessous, puis rouvrir l'application : l'autorisation n'est lue qu'au lancement, et redouble-cliquer sur l'icône ne relance rien.";
  $("autorisation-demander").hidden = charge.accordee;
}

async function demanderAutorisation() {
  await demander("/api/accessibilite/demander", { method: "POST" });
  afficherBandeau(
    "echec",
    "Autorisation demandée au système.",
    [
      "Cocher « Contrôle vocal » dans Réglages système, Confidentialité et sécurité, Accessibilité.",
      "Puis fermer et rouvrir l'application : l'autorisation n'est lue qu'au lancement.",
    ],
  );
  setTimeout(relireAutorisation, 1000);
}

async function fermerReglages() {
  const arret = etat.moteur.actif
    ? "La télécommande sera arrêtée avec les réglages. Fermer ?"
    : "Fermer les réglages ?";
  if (!window.confirm(arret)) return;

  // La réponse n'arrivera peut-être pas : le serveur se ferme en la disant. Un
  // échec de requête est donc ici le signe que ça a marché.
  try {
    await demander("/api/quitter", { method: "POST" });
  } catch (erreur) {
    void erreur;
  }
  document.body.replaceChildren(messageDeFermeture());
}

function messageDeFermeture() {
  const bloc = document.createElement("main");
  bloc.className = "page-frame ferme";
  const titre = document.createElement("h1");
  titre.textContent = "Réglages fermés";
  const note = document.createElement("p");
  note.textContent =
    "Cette page peut être fermée. Rouvrir l'application pour revenir.";
  bloc.append(titre, note);
  return bloc;
}

function remplirChoixProfils(profils) {
  const choix = $("option-profil");
  const retenu = choix.value;
  choix.replaceChildren();
  const automatique = document.createElement("option");
  automatique.value = "";
  automatique.textContent = "Suit l'application au premier plan";
  choix.append(automatique);
  for (const profil of profils) {
    if (profil.erreur) continue;
    const option = document.createElement("option");
    option.value = profil.nom;
    option.textContent = profil.nom;
    choix.append(option);
  }
  choix.value = retenu;
}

// --- Actions ----------------------------------------------------------------

async function chargerListe() {
  const { ok, charge } = await demander("/api/profils");
  if (!ok) return afficherBandeau("echec", "Liste des profils illisible.");
  // Installée en application, l'interface édite des CSV rangés dans la
  // bibliothèque de l'utilisateur : sans ce rappel, personne ne les retrouve
  // pour les sauvegarder ou les passer à un collègue.
  if (charge.dossier) $("dossier-profils").textContent = charge.dossier;
  rendreListeProfils(charge.profils);
  remplirChoixProfils(charge.profils);
  if (charge.profils.length === 0) {
    // Dossier vide, ce qui n'arrive qu'après avoir tout supprimé : sans ce cas,
    // l'en-tête et la table garderaient à l'écran le profil qui vient de partir.
    etat.profil = null;
    etat.lignes = [];
    $("titre-profil").textContent = "Aucun profil";
    $("sous-titre-profil").textContent = "En ajouter un par « + Un profil ».";
    $("supprimer-profil").disabled = true;
    return rendreTable();
  }
  if (!etat.profil) {
    await ouvrirProfil(charge.profils[0].nom);
  }
}

async function ouvrirProfil(nom) {
  const { ok, charge } = await demander(`/api/profils/${nom}`);
  if (!ok) {
    return afficherBandeau("echec", `Profil « ${nom} » illisible.`, [charge.erreur || ""]);
  }
  etat.profil = nom;
  etat.lignes = charge.lignes;
  $("titre-profil").textContent = nom;
  const application = charge.lignes.find((l) => l.application)?.application || "";
  const bundle = charge.lignes.find((l) => l.bundle_id)?.bundle_id || "aucun identifiant";
  $("sous-titre-profil").textContent = `${application} · ${bundle}`;
  $("lien-export").href = `/api/profils/${nom}/export`;
  $("lien-export").setAttribute("download", `${nom}.csv`);

  // Le serveur dit lequel se protège, la page ne le devine pas : c'est lui qui
  // refuserait, et son verdict est le seul qui compte.
  const supprimer = $("supprimer-profil");
  supprimer.disabled = Boolean(charge.protege);
  supprimer.title = charge.protege
    ? "Le profil de repli ne se supprime pas : sans lui, la télécommande refuse de démarrer."
    : `Supprimer le profil « ${nom} »`;
  $("bandeau").hidden = true;
  rendreTable();
  await chargerListe();
}

async function enregistrer() {
  const { ok, charge } = await demander(`/api/profils/${etat.profil}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lignes: etat.lignes }),
  });

  if (ok) {
    marquerRefus([]);
    afficherBandeau("succes", `Profil « ${etat.profil} » enregistré.`, [
      "Redémarrer la télécommande pour qu'elle le prenne : elle lit ses fichiers "
        + "au lancement, et garde en mémoire ce qu'elle y a trouvé.",
    ]);
    return chargerListe();
  }

  const refus = charge.refus || [{ ligne: 0, colonne: "", message: charge.erreur }];
  marquerRefus(refus);
  afficherBandeau(
    "echec",
    "Rien n'a été écrit, le fichier est intact.",
    refus.map((r) => (r.ligne ? `Ligne ${r.ligne} : ${r.message}` : r.message)),
  );
}

function ajouterLigne() {
  const modele = etat.lignes.find((l) => l.application) || {};
  const vide = Object.fromEntries(COLONNES.map((colonne) => [colonne, ""]));
  etat.lignes.push({
    ...vide,
    application: modele.application || "",
    bundle_id: modele.bundle_id || "",
    actif: "oui",
  });
  rendreTable();
  const dernier = document.querySelector('tr:last-child [data-colonne="commande"]');
  if (dernier) dernier.focus();
}

async function importer(fichier, nom = etat.profil) {
  const texte = await fichier.text();
  const { ok, charge } = await demander(`/api/profils/${nom}/import`, {
    method: "POST",
    headers: { "Content-Type": "text/csv" },
    body: texte,
  });
  if (ok) {
    // Le bandeau vient après l'ouverture, jamais avant : `ouvrirProfil` le
    // masque en repartant du fichier relu, et le succès passait inaperçu.
    await ouvrirProfil(nom);
    return afficherBandeau("succes", `« ${fichier.name} » importé dans « ${nom} ».`);
  }
  const refus = charge.refus || [{ ligne: 0, message: charge.erreur }];
  afficherBandeau(
    "echec",
    "Import refusé, le profil est intact.",
    refus.map((r) => (r.ligne ? `Ligne ${r.ligne} : ${r.message}` : r.message)),
  );
}

async function supprimerProfil() {
  const nom = etat.profil;
  if (!nom) return;
  // Le fichier part pour de bon, sans corbeille ni version antérieure : la
  // confirmation dit donc ce qui disparaît, et rappelle l'export d'à côté.
  const perdu = etat.lignes.length;
  if (
    !window.confirm(
      `Supprimer le profil « ${nom} » et ses ${perdu} ligne${perdu > 1 ? "s" : ""} ?\n\n`
        + "Le fichier est effacé pour de bon. « Exporter » en garde une copie avant.",
    )
  ) {
    return;
  }

  const { ok, charge } = await demander(`/api/profils/${nom}`, { method: "DELETE" });
  if (!ok) {
    return afficherBandeau("echec", `Suppression refusée, « ${nom} » est intact.`, [
      charge.erreur || "",
    ]);
  }

  // Plus de profil ouvert : `chargerListe` ouvre alors le premier qui reste.
  etat.profil = null;
  etat.lignes = [];
  await chargerListe();
  afficherBandeau("succes", `Profil « ${nom} » supprimé.`, [
    "Redémarrer la télécommande pour qu'elle cesse de l'écouter : elle lit ses "
      + "fichiers au lancement, et garde en mémoire ce qu'elle y a trouvé.",
  ]);
}

/* Nom proposé pour un profil créé : celui du fichier, ramené à la convention.
 * C'est une commodité, pas un contrôle : la page ne décide pas de ce qui est
 * valide, elle épargne seulement un aller-retour de refus sur « Chrome (1).csv ».
 * Le serveur garde le dernier mot, et son message s'affiche tel quel. */
function nomPropose(fichier) {
  return fichier.name
    .replace(/\.csv$/i, "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")   // dépose les accents restés à part
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

async function creerProfil(fichier) {
  const saisi = window.prompt(
    "Nom du nouveau profil, en minuscules, chiffres et soulignés :",
    nomPropose(fichier),
  );
  if (saisi === null) return;
  const nom = saisi.trim();

  const { ok, code, charge } = await demander(`/api/profils/${nom}/creer`, {
    method: "POST",
    headers: { "Content-Type": "text/csv" },
    body: await fichier.text(),
  });

  if (ok) {
    await ouvrirProfil(nom);
    return afficherBandeau("succes", `Profil « ${nom} » créé depuis « ${fichier.name} ».`, [
      "Redémarrer la télécommande pour qu'elle le prenne : elle lit ses fichiers "
        + "au lancement, et garde en mémoire ce qu'elle y a trouvé.",
    ]);
  }

  // Un profil du même nom est déjà là. Le remplacer se demande, il ne se devine
  // pas : l'ancien contenu n'a pas de version antérieure où revenir.
  if (code === 409) {
    const remplacer = window.confirm(
      `Le profil « ${nom} » existe déjà.\n\n`
        + `Remplacer tout son contenu par « ${fichier.name} » ? Ce qu'il contient sera perdu.`,
    );
    if (remplacer) return importer(fichier, nom);
    return afficherBandeau("echec", `Rien n'a été écrit : « ${nom} » existe déjà.`);
  }

  const refus = charge.refus || [{ ligne: 0, message: charge.erreur }];
  afficherBandeau(
    "echec",
    "Création refusée, aucun fichier n'a été écrit.",
    refus.map((r) => (r.ligne ? `Ligne ${r.ligne} : ${r.message}` : r.message)),
  );
}

// --- Amorçage ---------------------------------------------------------------

async function demarrer() {
  const { ok, charge } = await demander("/api/touches");
  if (ok) etat.touches = charge;
  rendreTouchesConnues();

  $("enregistrer").addEventListener("click", enregistrer);
  $("enregistrer-actions").addEventListener("click", enregistrerActions);
  $("ajouter").addEventListener("click", ajouterLigne);
  $("supprimer-profil").addEventListener("click", supprimerProfil);
  $("interrupteur").addEventListener("click", basculerMoteur);
  $("fermer").addEventListener("click", fermerReglages);
  $("autorisation-demander").addEventListener("click", demanderAutorisation);
  $("import").addEventListener("change", (evenement) => {
    const [fichier] = evenement.target.files;
    if (fichier) importer(fichier);
    evenement.target.value = "";
  });
  // Remis à vide après coup, sans quoi choisir deux fois le même fichier ne
  // déclencherait rien : le champ ne change pas de valeur.
  $("nouveau-profil").addEventListener("change", (evenement) => {
    const [fichier] = evenement.target.files;
    if (fichier) creerProfil(fichier);
    evenement.target.value = "";
  });

  await chargerActions();
  await chargerListe();
  await relireMoteur();
  await relireAutorisation();
  setInterval(relireMoteur, PERIODE_ETAT);
}

demarrer();
